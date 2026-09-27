# Build record - 10-normalise-instance-hosts

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/16-10-normalise-instance-hosts.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Normalise JoinPeerTube host entries on the Python side\n\n## Requirements\n\n### What was asked for\n\nBuild issue `docs/project/issues/06-normalise-instance-hosts.md` as triaged: Normalise JoinPeerTube host entries on the Python side with an exact port of the crawler's `normalizeHostToken`. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.\n\n### Purpose\n\nClose the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.\n\n### Decisions this rests on\n\nNo ADR. The decision is recorded in the issue's triage comment: an exact port, with no extra validation.\n\n### Agent Brief\n\n**Category:** bug\n**Summary:** Normalise JoinPeerTube host entries on the Python side with an exact port of the crawler's `normalizeHostToken`\n\n**Current behavior:**\nThree components read the same JoinPeerTube hosts list: the whitelist sync job, the updater worker's join-hosts fetch, and the TypeScript crawler. The crawler passes every entry through `normalizeHostToken` and skips entries that normalise to nothing. The two Python readers only trim and lowercase, so an entry such as `https://Tube.Example/` or `tube.example.` is stored as one string by the crawler and another by the Python jobs. The updater's comparisons (JoinPeerTube hosts vs hosts already in the database, and vs the instance denylist) then treat one instance as two, or miss a denylist match.\n\n**Desired behavior:**\nA Python function `normalize_host_token(value: str) -> str | None`, with a docstring, returns exactly what the crawler's `normalizeHostToken` returns for the same input:\n1. Trim surrounding whitespace and lowercase. If the result is empty, return None.\n2. If it starts with `http://` or `https://`: parse it as a URL and return its hostname, lowercased. Return None if the hostname is empty or parsing fails.\n3. Else, if it contains `/`: parse `https://` + value as a URL and return its hostname, lowercased. Return None if the hostname is empty or parsing fails.\n4. Else: return the value with all leading and trailing `.` removed, or None if that leaves nothing.\n\nThe whitelist sync job and the updater's join-hosts fetch both apply it to every entry, and skip entries that return None. Where the Python and WHATWG URL parsers differ on hostname extraction, the Python port matches the crawler. At minimum that covers userinfo (`user@host`), explicit ports, IPv6 literals (the crawler's hostname keeps the brackets), and internationalised names (the crawler returns punycode).\n\n**Key interfaces:**\n- New `normalize_host_token()` in a Python module importable by both jobs (the Engine server's shared `data` package already serves the jobs).\n- The whitelist sync job's host fetch (currently `fetch_hosts`) and the updater's `fetch_join_hosts()`: use it in place of `strip().lower()`.\n- The crawler's `normalizeHostToken()` in its host-filters module is the reference and is **not** changed.\n\n**Acceptance criteria:**\n- [ ] A table-driven Python test asserts `normalize_host_token` output for at least these inputs, with the expected value being what `normalizeHostToken` returns: `\" Tube.Example \"`, `\"tube.example.\"`, `\"..tube.example..\"`, `\"https://Tube.Example/\"`, `\"http://tube.example:8080/path\"`, `\"https://user@tube.example\"`, `\"tube.example/videos\"`, `\"tube.example:9000\"`, `\"https://[::1]:8080/\"`, `\"https://b\u00fccher.example/\"`, `\"\"`, `\"   \"`, `\".\"`, `\"https://\"`.\n- [ ] The same inputs and expected values are checked against the TypeScript `normalizeHostToken` (a crawler unit test or a fixture both sides read), so the two implementations cannot drift unnoticed.\n- [ ] The whitelist sync job, given a hosts payload containing `\"https://Tube.Example/\"` and `\"tube.example\"`, stores the single host `tube.example`.\n- [ ] Entries for which the helper returns None are not stored by either job, and the job still completes.\n- [ ] The updater's join-hosts set for the same payload equals the set the sync job stores.\n- [ ] Existing moderation-integration and orchestrator smoke tests pass.\n\n**Out of scope:**\n- Changing `normalizeHostToken` or any crawler behaviour.\n- Any validation stricter than `normalizeHostToken` (IP literals, ports, userinfo, characters).\n- Rewriting host rows already stored in `instances`.\n- `data.moderation.normalize_host` and the denylist/moderation CLIs.\n- `compare-join-hosts.py`.\n\n### Consistency constraints\n\n- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.\n- Backwards compatibility is not required beyond what the brief states.\n- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.\n\n### Batch context\n\nPart of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.\n\nWave 1. It touches no file that another batch issue touches.\n\n### Conflicts\n\nThe brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.\n\n## High-level plan\n\n### Approach\n\nAdd `normalize_host_token()` to a module in the Engine's shared `engine/server/data` package, which both jobs already import. It follows the brief's four numbered rules and uses `urllib.parse` to extract the hostname. Where that differs from WHATWG `URL`, it handles the case explicitly: userinfo is stripped, the port is stripped, IPv6 literals keep their brackets, and internationalised names are encoded to punycode (IDNA). `fetch_hosts` in `sync-whitelist.py` and `fetch_join_hosts` in `updater-worker.py` call it in place of `strip().lower()` and skip entries that return None.\n\nDrift protection: one JSON fixture of `input -> expected` pairs covers every input the brief lists. The Python test checks `normalize_host_token` against the fixture. The same test then runs Node on the crawler's compiled `engine/crawler/dist/host-filters.js` over the same inputs and asserts identical output. The expected values are therefore the crawler's own, and the two sides cannot drift unnoticed.\n\n### Alternatives considered\n\n- **A crawler-side test runner** (vitest or node:test in `engine/crawler`) reading the fixture. Rejected: the crawler has no test script or runner today (`engine/crawler/package.json`), and one Python test that invokes Node covers both sides from the suite that already runs.\n- **Hand-written expected values without running the TS side.** Rejected: that tests Python against the author's reading of WHATWG, which is where drift hides.\n- **Reusing `data.moderation.normalize_host`.** Rejected by the triage decision: it is the lenient normaliser for operator input and stays separate.\n\n### Risks and limitations\n\n- `dist/host-filters.js` must exist and match `src/`. When `dist` is missing or older than `src`, the test must fail loudly rather than skip, or it runs `npm run build` first. The build chooses which at its checkpoint.\n- `urllib.parse` and WHATWG differ on edge inputs beyond the listed set (for example percent-encoding and backslashes). Only the listed inputs are pinned; others may differ. The fixture can grow to cover them later.\n- Hosts already stored under the old spelling are not rewritten (out of scope), so one updater run after the change may treat the old and new spellings as different hosts.\n- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.\n- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).\n\n### Tradeoffs accepted\n\nA Python test depends on Node and on the crawler's compiled output being present.",
  "request_source": "read from docs/project/plans/10-normalise-instance-hosts.md",
  "slug": "10-normalise-instance-hosts",
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
      "name": "Python port of normalizeHostToken",
      "checkpoint": "Seam: the pure function `data.moderation.normalize_host_token`, called directly from pytest with `engine/server` added to sys.path, following test_db.py:22-26 (`SERVER_DIR` insert plus a `# noqa: E402` import) and `ROOT` from conftest as test_similar.py uses it. The test is parametrised over the pairs loaded at run time from `tests/active/host_tokens.json` (15 pairs, with ids from repr(input)). It asserts `normalize_host_token(input) == expected`, with JSON null standing for None. Together the pairs exercise all four branches, userinfo, port drop, port keep in branch 4, IPv6 re-bracketing, punycode, the None cases and dot keeping in URL form. It runs in the normal validate_tests.py pass because it uses no Engine fixture.",
      "intent": "`engine/server/data/moderation.py` gains `normalize_host_token`, placed directly after the unchanged `normalize_host`, and it returns the pinned value for every pair in `tests/active/host_tokens.json`.",
      "clauses": [
        {
          "id": "C1",
          "text": "`normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null."
        }
      ],
      "files": [
        "engine/server/data/moderation.py (EDITED)",
        "tests/active/host_tokens.json (NEW)",
        "tests/active/test_host_normalisation.py (NEW)"
      ],
      "done": true,
      "outcome": "Nothing needed writing this turn. All three files in this phase were already in the worktree when the turn started. I checked each against the crawler source and the checkpoint's pinned values, and left them unchanged. I did not write them in this turn, so they came from an earlier pass over this step.\n\n### `engine/server/data/moderation.py`\n- `normalize_host_token(value: str) -> str | None` sits directly after `normalize_host`, which is unchanged. It is a line-for-line port of `normalizeHostToken` in `engine/crawler/src/host-filters.ts`:\n  - strips and lowercases the input, and returns None if nothing is left;\n  - sends `http://` / `https://` inputs through `_whatwg_hostname`;\n  - sends inputs containing `/` through `_whatwg_hostname` as `https://{raw}`;\n  - otherwise strips leading and trailing dots, returning None if nothing is left;\n  - catches a single `ValueError`, which stands in for the crawler's try/catch around the whole body.\n- `_whatwg_hostname(url)` is a private helper that returns the hostname WHATWG `URL.hostname` would give:\n  - reads `urlparse(...).port` so a bad port raises, as WHATWG does;\n  - returns None for an empty host;\n  - puts brackets around the compressed form of IPv6 literals;\n  - IDNA-encodes only non-ASCII hosts.\n  - It carries a `rat-tail:` comment: `urlparse` accepts forbidden host code points that WHATWG rejects, so the two only match on the pinned inputs. The fix is a forbidden-code-point check in this helper once a fixture input exposes the gap.\n- The module header comment names both normalisers and what each is for.\n- New imports: `ipaddress` and `urlparse`. New module constant: `URL_SCHEME_PREFIXES`.\n\n### `tests/active/host_tokens.json`\n- Contains exactly the 15 `{\"input\", \"expected\"}` pairs from the requirements, with `null` meaning None. I compared them one by one against the checkpoint's `PINNED` dict and they match.\n\n### `tests/active/test_host_normalisation.py`\n- A durable test, parametrised over every pair in `host_tokens.json`, that asserts `normalize_host_token(input) == expected`. It gets `ROOT` from `tests/active/conftest.py`, which I confirmed exports it.\n\n### What I ran\n- I wrote a probe, `tests/tmp/probe_host_token.py`, that runs all 15 fixture pairs through `normalize_host_token` and asserts none of them mismatch. It passed (exit 0). I did not run the gating checkpoint myself.\n- I have no delete tool, so the probe is still in the tree. The operator can remove it with `rm tests/tmp/probe_host_token.py`; it gates nothing."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Crawler parity and loud failure",
      "checkpoint": "Seam, clause 1: the crawler's compiled module `engine/crawler/dist/host-filters.js`, entered by one `node --input-type=module -e` subprocess. The subprocess imports that module by its file:// URL (passed in the HOST_FILTERS_URL env var), reads the fixture inputs as JSON on stdin and prints `normalizeHostToken` of each as JSON. The test asserts returncode 0 and that dict(zip(inputs, outputs)) equals the pinned {input: expected} map. Because phase 1 checks Python against the same map, passing this proves Python == crawler on the fixture. Seam, clause 2: the pytest outcome of the node test itself. The checkpoint runs `python -m pytest tests/active/test_host_normalisation.py -k crawler_dist` in a subprocess three times: with a PATH that lacks node, with DIST pointed at a missing path, and with a stale dist. It asserts each run reports failed, not skipped, and that the message names the build hint. The staleness rule is settled here: compare the git commit times of src/host-filters.ts and dist/host-filters.js; fall back to mtime when src has uncommitted changes or either file has no history; a missing git is a failure.",
      "intent": "`test_host_normalisation.py` checks the crawler's compiled `normalizeHostToken` against the same pinned fixture, and the check cannot pass without node and a current `dist/host-filters.js`.",
      "clauses": [
        {
          "id": "C1",
          "text": "`dist/host-filters.js` run under node returns each fixture pair's expected value."
        },
        {
          "id": "C2",
          "text": "A missing node, a missing dist or a stale dist makes the crawler test fail rather than skip."
        }
      ],
      "files": [
        "tests/active/test_host_normalisation.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `tests/active/test_host_normalisation.py`\n- I added one test, `test_crawler_dist_returns_pinned_values`. It is not parametrized, so `-k crawler_dist` selects exactly that one test. It runs through these checks in order:\n  1. `node` must be on PATH. If not, it fails with the build hint `cd engine/crawler && npm install && npm run build`.\n  2. `DIST` must exist. If not, it fails with the build hint.\n  3. `git` must be on PATH. If not, it fails and names git.\n  4. `DIST` must not be older than `SRC`. If it is, it fails with the build hint.\n  5. It loads `DIST` in node through its file:// URL, runs `normalizeHostToken` on every input in `host_tokens.json`, and fails if any value differs. The message lists each wrong input with `repr(actual)` and `repr(expected)`, and has no build hint.\n- `_dist_is_stale` decides step 4:\n  - When both files are committed and clean, it compares git commit times (`git log -1 --format=%ct`) with a strict `>`. A checkout sets file mtimes arbitrarily, so on a clean tree they mean nothing.\n  - When either file shows in `git status --porcelain` (an edit, or never committed) or has no commit, it compares mtimes instead.\n  - git runs from `ROOT`, so `GIT_DIR`/`GIT_WORK_TREE` in the environment can point it at another repo.\n- The paths are the module-level `Path` constants `SRC` and `DIST`, read when the test runs, not at import. `BUILD_HINT` and `NODE_SCRIPT` are also module level.\n- The module docstring has a new bullet for the crawler test. Added imports: `os`, `shutil`, `subprocess`.\n- Nothing calls `pytest.skip`, so a missing prerequisite always fails the test.\n\n### Probe (checked, then emptied)\nI ran a throwaway probe, `tests/tmp/probe_git_outside_worktree.py`, and saw:\n- With `GIT_DIR`/`GIT_WORK_TREE` set and git run from outside that work tree, absolute pathspecs work. `status` shows `??` for an untracked file and ` M` for an edited one, and `log` gives no output for a file never committed.\n- In the real tree, src and dist are clean and both have commit time 1790369883.\n- The new durable test passes on this tree when run in its own pytest with junit output.\n- A long custom assert message comes through complete in junit's `message` attribute.\n- Python is 3.14, so `zip(strict=True)` is available.\n\nI haven't run the checkpoint itself, so none of its other scenarios have been seen passing yet: wrong values, missing node/git/dist, and the stale and not-stale git cases. The workflow's run of the checkpoint will be the first check of those. I had no delete tool, so the probe file is emptied to a docstring and still needs deleting.",
      "beyond": "tests/tmp/probe_git_outside_worktree.py \u2014 the probe I used to check git behaviour and the junit message before writing the test. It now holds only a docstring (no tests) because I had no delete tool; please delete it."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Both jobs normalise through the helper",
      "checkpoint": "Seam: the two jobs' fetch functions and `sync_hosts`. Both job files are loaded with importlib.util.spec_from_file_location, following the test_similar.py:36-41 precedent, in a module-scoped fixture. Payloads are served from tmp_path as file:// URIs, so no server and no network are needed. Clause 1: a list-shape payload [\"https://Tube.Example/\", \"tube.example\"] gives {\"tube.example\"} from `fetch_hosts`. `ensure_whitelist_schema` plus `sync_hosts` into a tmp_path SQLite file (never the shared whitelist.db) returns (1, 0, 1) and stores exactly the one row \"tube.example\". Clause 2: a dict-shape payload mixing \"\", \"   \", \".\", \"https://\" with valid entries gives {\"tube.example\", \"other.example\"} from both `fetch_hosts` and `fetch_join_hosts`. Regression guard, not a new clause: `fetch_hosts` on a payload where every entry normalises to None still raises ValueError \"Whitelist contained no hosts.\". After the phase, run test-moderation-integration.py, test-orchestrator-smoke.py (report it as not run if node, dist, the embedding stack or network is missing) and validate_tests.py from the worktree, compared with the green baseline.",
      "intent": "`fetch_hosts` in sync-whitelist.py and `fetch_join_hosts` in updater-worker.py pass every hosts-list entry through `normalize_host_token` in place of `strip().lower()`.",
      "clauses": [
        {
          "id": "C1",
          "text": "`fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`, which `sync_hosts` stores as one row."
        },
        {
          "id": "C2",
          "text": "Entries that normalise to None are dropped, and `fetch_join_hosts` returns the same host set as `fetch_hosts`."
        }
      ],
      "files": [
        "engine/server/db/jobs/sync-whitelist.py (EDITED)",
        "engine/server/db/jobs/updater-worker.py (EDITED)",
        "tests/active/test_host_normalisation.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/db/jobs/sync-whitelist.py`\n- The `data.moderation` import now also brings in `normalize_host_token`.\n- In `fetch_hosts`, each entry is now normalised with `host_value = normalize_host_token(str(host))` instead of `str(host).strip().lower()`. The existing `if host_value:` guard already drops `None`, so entries that normalise to nothing are skipped. When no host is left, the function still raises `ValueError(\"Whitelist contained no hosts.\")`. The User-Agent, error handling and payload-shape handling are unchanged.\n\n### `engine/server/db/jobs/updater-worker.py`\n- `normalize_host_token,` is added to the parenthesised `data.moderation` import, between `list_active_denied_hosts` and `purge_host_data`.\n- `fetch_join_hosts` makes the same swap: `value = normalize_host_token(str(host))`. The existing `if value:` guard drops `None`. `list_prod_hosts` is untouched, as the plan says.\n\n### `tests/active/test_host_normalisation.py`\n- The module docstring has two new bullets covering the job behaviour.\n- New imports: `importlib.util` and `sqlite3`. New constant: `JOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"`.\n- New helpers:\n  - `_load_job` loads a job file with `spec_from_file_location`.\n  - a module-scoped `jobs` fixture loads both jobs.\n  - `_payload_url` writes the payload to `tmp_path` and returns a `file://` URI.\n- Three new durable tests, one for each behaviour this phase delivers:\n  - `test_sync_job_stores_one_spelling_per_host`: a list payload with `https://Tube.Example/` and `tube.example` gives `{\"tube.example\"}`. `sync_hosts` on a temp SQLite database returns `(1, 0, 1)` and stores the single row `tube.example`.\n  - `test_jobs_drop_entries_that_normalise_to_none`: a `{\"data\": [...]}` payload with `\"\"`, `\"   \"`, `\".\"` and `\"https://\"` plus two valid entries gives `{\"tube.example\", \"other.example\"}` from both `fetch_hosts` and `fetch_join_hosts`.\n  - `test_sync_job_still_rejects_a_list_with_no_usable_host`: `fetch_hosts` raises `ValueError` with exactly \"Whitelist contained no hosts.\".\n\n### What I ran\n- I ran `ValidateTests tests/active/test_host_normalisation.py -k job`: 3 passed, 16 deselected, exit 0.\n- I did not run the gating checkpoint. It exercises the same functions on the same inputs.\n- I did not run the post-phase commands the plan lists: test-moderation-integration.py, test-orchestrator-smoke.py and the full validate_tests.py compared with the green baseline. They are still owed, and the smoke test counts as not run if node, dist, the embedding stack or the network is missing."
    }
  ],
  "digests": {
    "tests/tmp/test_10_normalise_instance_hosts_phase1.py": "4e299898a7854f2e23c1537737dbcb15c2cf628d166a577115d57bde47dbab1e",
    "tests/tmp/test_10_normalise_instance_hosts_phase2.py": "9213297630d3a617eac01e8a295fe9a6a84951a95e9a27268b0da09bdde5ca98",
    "tests/tmp/test_10_normalise_instance_hosts_phase3.py": "39aac335d65349c02b94bf8515c1d390875a31e6271bef928f0654e8e1ef272a"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260926T185353-6acf-dev-flow",
    "20260926T191830-74c8-dev-flow"
  ],
  "plan": "docs/project/plans/16-10-normalise-instance-hosts.md",
  "record": "docs/project/plans/16-10-normalise-instance-hosts.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### What is being built\n\nIssue `docs/project/issues/06-normalise-instance-hosts.md` (plan `docs/project/plans/10-normalise-instance-hosts.md`, security hardening batch wave 1), category bug. The work is an exact Python port of the crawler's `normalizeHostToken` (`engine/crawler/src/host-filters.ts`, the exported function near line 83). The two Python readers of the JoinPeerTube hosts list will use it: `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py` (function at about line 219, the `str(host).strip().lower()` at about line 243) and `fetch_join_hosts` in `engine/server/db/jobs/updater-worker.py` (function at about line 414, the `strip().lower()` at about line 438). Once earlier waves merge, line numbers will drift, so find these by function name.\n\n### Purpose\n\nThree components read the same JoinPeerTube hosts list: `sync-whitelist.py`, `updater-worker.fetch_join_hosts`, and the TypeScript crawler. Only the crawler normalises. As a result one entry can be stored under two spellings, and the updater gets new/stale host sets wrong and misses denylist matches. After this build, both Python jobs produce the same string as the crawler for the same entry. That closes audit finding SI4-M1 (task 86) as far as the triage decision allows: an exact port, with no validation beyond what `normalizeHostToken` does.\n\n### The helper\n\n- `normalize_host_token(value: str) -> str | None`, with a docstring, in a module of the Engine's shared `engine/server/data` package. Both jobs already put `engine/server` on `sys.path` and import `data.moderation`. Whether it goes in a new module or an existing one is a design decision for the next step. Fewest files is preferred. It must not change `data.moderation.normalize_host`.\n- It returns exactly what `normalizeHostToken` returns for the same input:\n  1. `value.strip().lower()`. If that is empty, return None.\n  2. If it starts with `http://` or `https://`, parse it as a URL and return the hostname, lowercased. Return None if the hostname is empty or parsing fails.\n  3. Else, if it contains `/`, parse `https://` + value and return the hostname, lowercased. Return None if the hostname is empty or parsing fails.\n  4. Else, return the value with every leading and trailing `.` removed, or None if nothing is left. No URL parse happens in this branch, so ports, `@`, `?`, `#` and non-ASCII characters are kept as they are.\n- In branches 2 and 3 the Python parser (stdlib `urllib.parse`, no new dependency) must match the WHATWG `URL.hostname`:\n  - userinfo is dropped (`user@host` \u2192 `host`)\n  - the port is dropped\n  - IPv6 literals keep their brackets: `urlparse(...).hostname` returns `::1` and the crawler returns `[::1]`\n  - internationalised names are returned as punycode (`b\u00fccher.example` \u2192 `xn--bcher-kva.example`)\n  - input WHATWG rejects returns None\n- Branch 4 does no punycode conversion, matching the crawler.\n\n### Pinned expected values\n\nThese inputs go into one JSON fixture of input \u2192 expected pairs that both the Python and the Node side read. Expected values are the WHATWG results; the Node check confirms them against the crawler's real output:\n- `\" Tube.Example \"` \u2192 `\"tube.example\"`\n- `\"tube.example.\"` \u2192 `\"tube.example\"`\n- `\"..tube.example..\"` \u2192 `\"tube.example\"`\n- `\"https://Tube.Example/\"` \u2192 `\"tube.example\"`\n- `\"http://tube.example:8080/path\"` \u2192 `\"tube.example\"`\n- `\"https://user@tube.example\"` \u2192 `\"tube.example\"`\n- `\"tube.example/videos\"` \u2192 `\"tube.example\"`\n- `\"tube.example:9000\"` \u2192 `\"tube.example:9000\"` (branch 4, the port is kept)\n- `\"https://[::1]:8080/\"` \u2192 `\"[::1]\"`\n- `\"https://b\u00fccher.example/\"` \u2192 `\"xn--bcher-kva.example\"`\n- `\"\"` \u2192 null\n- `\"   \"` \u2192 null\n- `\".\"` \u2192 null\n- `\"https://\"` \u2192 null (WHATWG throws; the crawler returns null)\n\nThe fixture may grow; every input in it must pass on both sides.\n\n### Job changes\n\n- `fetch_hosts` (sync-whitelist) and `fetch_join_hosts` (updater) each replace `str(host).strip().lower()` with `normalize_host_token(str(host))` and skip entries that return None. Nothing else changes in either function: the fetch, the payload shape handling (`{\"data\": [...]}` or a list, with `host` taken from dicts), the User-Agent strings, the error types and messages.\n- `fetch_hosts` still raises `ValueError(\"Whitelist contained no hosts.\")` when no entry survives. That is existing behaviour. \"The job still completes\" means a payload in which some entries return None.\n- `list_prod_hosts`, `load_denied_hosts`, `compare-join-hosts.py`, `data.moderation.normalize_host`, the denylist/moderation CLIs and all crawler code stay unchanged.\n\n### Acceptance criteria\n\n- A table-driven Python test asserts `normalize_host_token` against every fixture pair.\n- The same test runs Node on the crawler's compiled `engine/crawler/dist/host-filters.js`, calling its exported `normalizeHostToken` over the same fixture inputs, and asserts that its output equals the fixture's expected value, and so equals the Python output. `dist/host-filters.js` is present in this worktree and its `normalizeHostToken` matches `src/host-filters.ts`.\n  - If `node` is missing, or `dist` is missing or older than `src/host-filters.ts`, the test must fail loudly, never skip, or it builds first. The build checkpoint chooses which.\n  - `engine/crawler/node_modules` (and so `tsc`) is not guaranteed in a fresh worktree, so the fail-loudly option does not depend on it.\n- Given a hosts payload containing `\"https://Tube.Example/\"` and `\"tube.example\"`, the whitelist sync job's host fetch returns the single host `tube.example`, which the job then stores through `sync_hosts`. The payload can be served from a local stdlib HTTP server or a `file://` URL, as `test-orchestrator-smoke.py` already serves `whitelist.json`.\n- Entries for which the helper returns None (for example `\"\"`, `\".\"`, `\"https://\"`) are not in either job's host set, and the fetch completes as long as at least one entry survives.\n- `fetch_join_hosts` returns, for the same payload, the same set as `fetch_hosts`.\n- The existing standalone scripts `engine/server/db/jobs/tests/test-moderation-integration.py` and `engine/server/db/jobs/tests/test-orchestrator-smoke.py` still pass. They are not part of `validate_tests.py`'s `tests/active` suite and are run separately.\n- The `tests/active` suite still passes through `validate_tests.py`.\n\n### Tests: placement and running\n\n- The new test is a pytest file in `tests/active` (the active tree; the working tree is `tests/tmp`, the archive `tests/archive`). Its JSON fixture sits beside it or in another path both sides can read. The job scripts have hyphenated filenames, so the test loads them with `importlib` (spec from file location), as they cannot be imported normally.\n- The new test needs no Engine, so the Engine rate-limit rule, which says Engine-backed files run in their own `validate_tests.py` invocations, does not apply to it. It still applies to the Engine-backed files already in `tests/active`.\n- Run `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts`, the `project_dir` in this worktree's `.un/skills/devsecops/config.json`. The record is `tests/last_test_validation.json` and the output `tests/last_test_output.txt`.\n- Adding a `test_groups` entry mapping the new test file to the helper module and the two job files happens at harvest on main, not in this worktree.\n\n### Baseline suite state\n\nBefore the build the suite ran green: exit code 0, variant false. Any red after the build was introduced by the build.\n\n### Style and constraints\n\n- New code follows the file it lands in:\n  - `\"\"\"Handle ...\"\"\"`-style or descriptive one-line docstrings\n  - `from __future__ import annotations` where the module already uses it\n  - module-level named constants\n  - stdlib only\n  - one statement or comment per line, no softwrapping\n- No new dependency. No interface with only one implementation.\n- Backwards compatibility is not required beyond what is stated here.\n\n### Out of scope\n\n- Changing `normalizeHostToken` or any crawler behaviour.\n- Any validation stricter than `normalizeHostToken`: IP literals, ports, userinfo, characters.\n- Rewriting host rows already stored in `instances`.\n- `data.moderation.normalize_host` and the denylist/moderation CLIs.\n- `compare-join-hosts.py`.\n- The orchestrator smoke test's own `strip().lower()` host reader.\n\n### Known limitations, accepted\n\n- An entry with no scheme and no `/` goes through branch 4 and is stored almost as given. So `evil@tube.example`, `host?x`, `host#y` and `tube.example:9000` are stored with those characters. The audit's `/ ? # @` concern is closed only for entries that go through the URL branches. This follows from the settled exact-port decision; the operator accepted it.\n- `urllib.parse`/`idna` and WHATWG may still differ on inputs outside the fixture:\n  - percent-encoding and backslashes\n  - IDNA 2003 (Python's `idna` codec) versus UTS #46 (WHATWG), for example `\u00df`\n  - JS `trim()` versus Python `strip()` on characters such as U+FEFF and U+001C-U+001F\n  - `toLowerCase()` versus `lower()` on characters such as `\u0130`\n  - Only the fixture inputs are pinned. The upgrade path is to add inputs to the fixture; the Node check then shows any mismatch.\n- `data.moderation.normalize_host`, used for denylist input, returns IPv6 without brackets and does not convert to punycode. A denylist entry for an IDN or IPv6 host may therefore not match the new spelling. This is out of scope.\n- Hosts already stored under the old spelling are not rewritten, so one updater run after the change may treat the old and new spellings as different hosts.\n- The Python test depends on Node and on the crawler's compiled `dist` being present and current.\n\n### Batch and worktree context\n\n- Wave 1 of the security hardening batch (`.scratch/security-hardening-batch/notes.md`), in worktree `.worktrees/fix-10-normalise-instance-hosts`. The build touches no file another batch issue touches: 05 and 02 edit `engine/server/data/interaction_events.py`, `similar.py` and others, not the files above.\n- `whitelist.db` is symlinked to the main tree and shared with other lanes. The new test does not touch it.\n- When merging, the tracked `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n- Harvest happens on main after the merge.\n</requirements>\n\n<conflicts>\nPurpose (\"close the security-audit finding\" SI4-M1, which cites entries containing `/ ? # @` reaching URL construction verbatim) vs the settled triage decision \"exact port, no extra validation\": in branch 4 of `normalizeHostToken` (engine/crawler/src/host-filters.ts), an entry with no scheme and no `/` (e.g. `evil@tube.example`, `host?x`) is only trimmed, lowercased and stripped of dots, so the finding is closed only for entries that go through the URL branches. The operator accepted this as a known limitation.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\n**Where the helper goes.** `normalize_host_token` goes into the existing `engine/server/data/moderation.py`, placed directly after `normalize_host`. That module is already the shared place for host normalisation (its header comment lists it). Both jobs already import from it: `sync-whitelist.py` has a single-line `from data.moderation import ...` and `updater-worker.py` has a parenthesised import. It already imports `urlparse` and uses `from __future__ import annotations`. So the port needs no new file, and each job only adds one name to an import it already has. The new function's docstring follows the file's descriptive one-line style. It must state that the function is an exact port of the crawler's `normalizeHostToken` and differs from `normalize_host` (which is left untouched), so a later reader does not merge the two. Any constants go at module level.\n\n**How the helper works.** It follows the four branches of `normalizeHostToken` (`engine/crawler/src/host-filters.ts:83`) in the same order:\n1. Strip and lowercase the input. If the result is empty, return None.\n2. If it starts with `http://` or `https://`, parse it as a URL and derive the WHATWG-style hostname.\n3. Else, if it contains `/`, parse `https://` + value and derive the hostname the same way.\n4. Else, return the value with leading and trailing dots stripped, or None if nothing is left.\n\nBranch 4 never calls the parser. That keeps `tube.example:9000` as it is and does no punycode conversion, as the crawler does.\n\n**Deriving the hostname in branches 2 and 3.** One private step turns `urllib.parse.urlparse` output into the value WHATWG `URL.hostname` would give:\n- **Userinfo and port.** `.hostname` already drops userinfo and the port and lowercases the host.\n- **Port validity.** The step also reads `.port`. Python raises ValueError on a port that is non-numeric or above 65535, which is input WHATWG also rejects. This costs one attribute read.\n- **Empty host.** If the host is missing (`https://`), return None, as the crawler does when `new URL` throws.\n- **IPv6 literals.** `.hostname` returns `::1` without brackets. When the host contains `:`, pass it through stdlib `ipaddress.IPv6Address`. That validates it (invalid gives None, like a WHATWG throw) and gives the compressed form WHATWG serialises. Then put the brackets back, giving `[::1]`. Unbalanced brackets make `urlparse` itself raise ValueError, which becomes None.\n- **Internationalised names.** If the host is not ASCII, encode it with the stdlib `idna` codec to get punycode (`xn--bcher-kva.example`). A UnicodeError becomes None. ASCII hosts are not sent through the codec. The codec rejects empty labels and labels over 63 characters, which WHATWG accepts for ASCII names (`https://a..b/` gives `a..b`), so running ASCII hosts through it would add rejections the crawler does not make.\n- **Errors.** ValueError and UnicodeError are caught around the parse, the same way the crawler's `try/catch` wraps its whole body.\n\n**Requirement: both jobs use it.** In `fetch_hosts` (`sync-whitelist.py`, the `strip().lower()` line inside the entry loop) and in `fetch_join_hosts` (`updater-worker.py`, the same line), that expression is replaced with `normalize_host_token(str(host))`. The following `if host_value:` / `if value:` guard already skips None, so the loop needs no other change. The fetch, the User-Agents, the payload-shape handling and the error messages stay the same. `fetch_hosts` still raises `ValueError(\"Whitelist contained no hosts.\")` when no entry survives. `list_prod_hosts` (the other `strip().lower()` in the updater, at about line 449) is deliberately left alone.\n\n**Requirement: the fixture and the table-driven test.** A new pytest file in `tests/active` (working name `test_host_normalisation.py`), with a JSON fixture beside it (`host_tokens.json`). The fixture is a list of `{input, expected}` pairs holding the 14 pinned values, with null for None. The test has three parts:\n- **Python side.** A parametrised test asserts `normalize_host_token(input) == expected` for every pair. It imports the helper after adding `engine/server` to `sys.path`, as the jobs do.\n- **Node side.**\n  - It runs `node --input-type=module` once, with a short inline script. The script imports `engine/crawler/dist/host-filters.js` by `file://` URL, reads the fixture inputs as JSON on stdin, maps them through `normalizeHostToken` and prints JSON on stdout.\n  - The Python test then asserts that each Node result equals the expected value. Together with the Python-side assertions, that also proves Python output equals crawler output.\n  - `dist/host-filters.js` imports only `node:fs`, and the crawler package is `\"type\": \"module\"`, so no `node_modules` is needed.\n- **Job side.**\n  - Both job files are loaded with `importlib.util.spec_from_file_location`. Their top-level code only sets up `sys.path` and parses `engine/crawler/schema.sql`, and `main()` sits behind `__name__` guards, so loading them has no side effects.\n  - A payload is written to `tmp_path` and served as a `file://` URL. `urlopen` handles `file:` even with a `Request` that carries headers, so no server thread is needed.\n  - One test checks that `[\"https://Tube.Example/\", \"tube.example\"]` gives `{\"tube.example\"}` from `fetch_hosts`. It then stores that set through `ensure_whitelist_schema` + `sync_hosts` into a temporary SQLite file (never the shared `whitelist.db`) and checks the stored row.\n  - A second test mixes `\"\"`, `\".\"`, `\"https://\"` with valid entries. It asserts the invalid entries are absent, the fetch completes, and `fetch_join_hosts` returns the same set as `fetch_hosts`. It uses the dict shape (`{\"data\": [{\"host\": ...}]}`) so both payload shapes are covered.\n  - The file uses no Engine fixture, so it runs in the normal `validate_tests.py` pass.\n\n**Requirement: loud failure, never skip.** Before the Node call, the test fails with `pytest.fail` and a message naming the fix in three cases:\n- `node` is not on PATH (found via `shutil.which`)\n- `dist/host-filters.js` is missing\n- `dist` is stale\n\nI recommend fail-loudly over build-first. Building needs `engine/crawler/node_modules/typescript`, which a fresh worktree does not have, so build-first would add a second failure mode and would also write to the tree during a test run. The build checkpoint makes the final choice.\n\n**Requirement: existing scripts and suite still pass.** After the build, run `test-moderation-integration.py` and `test-orchestrator-smoke.py` separately. Then run `validate_tests.py` from the worktree's `project_dir` and compare against the green baseline. The smoke test serves `whitelist.json` through `fetch_hosts`. Its plain hosts come out of the new helper unchanged, so its expectations still hold.\n\n### Alternatives considered\n\n- **New module (`data/hosts.py`) instead of `moderation.py`.** It would keep the file's name tied to moderation, but it adds a file and a second import line in each job. The requirements prefer the fewest files, and `moderation.py` already owns host normalisation. Rejected. The cost: at harvest, the `test_groups` entry maps the new test to all of `moderation.py`, so edits to that module will also trigger this test. That is cheap because the test needs no Engine.\n- **Porting the WHATWG host parser by hand, or adding a dependency such as `idna` or a WHATWG URL library.** Either would match the crawler on more inputs. Hand-porting is a large amount of code for inputs the list does not contain, and a dependency is ruled out. Rejected in favour of `urlparse` plus the small fixes above, with the fixture as the safety net.\n- **Producing the expected values with Node at test time instead of pinning them.** That would make the crawler the only oracle, and a crawler regression would pass silently. The settled design pins the WHATWG values and checks both sides against them. Kept.\n- **Checking whether `dist` is stale by modification time (mtime).** See the risks below. The recommended alternative is git-based: `dist` is stale when `src/host-filters.ts` has uncommitted changes, or when its last commit is newer than the last commit of `dist/host-filters.js`. Use mtime only when the files are untracked. This avoids false failures after a checkout while still catching a source edit that was never rebuilt.\n- **Sending ASCII hosts through the `idna` codec too.** Rejected. It would add rejections (empty or over-long labels) that WHATWG does not make for ASCII hosts.\n\n### Gotchas and risks\n\n- **An mtime-only staleness check breaks fresh clones.** `dist` appears to be tracked in git (no ignore rule). Git writes files in index order, and `dist/` sorts before `src/`, so a fresh checkout usually leaves `dist/host-filters.js` a few milliseconds *older* than `src/host-filters.ts`. A plain \"dist older than src\" check would then fail on a clean tree whose contents match. Hence the git-based rule recommended above. The build checkpoint should settle the rule explicitly, because \"older than\" in the requirements does not say how age is measured.\n- **The Node side runs the compiled `dist`, not `src`.** Parity is only as good as `dist` being current, which is why the staleness check exists.\n- **IDNA 2003 versus UTS #46.** Python's `idna` codec is IDNA 2003 and WHATWG uses UTS #46 (for example `\u00df` maps to `ss` in Python but `xn--zca` in WHATWG). This is accepted and not pinned. Adding such an input to the fixture would make the test fail by design.\n- **IPv4 shorthand.** WHATWG rewrites forms such as `0x7f.1` or `127.1` to `127.0.0.1`. `urlparse` does not. Not pinned, and accepted under the \"outside the fixture\" limitation.\n- **Forbidden host characters.** WHATWG rejects hosts containing characters such as a space, `<`, `>` or `^`. `urlparse` accepts them. A single module-level set of forbidden host code points could close this. I leave it out as speculative, and it can be added the first time a fixture input exposes the gap. This is a deliberate simplification: the ceiling is non-parity on such inputs, and the upgrade is that one constant and a check.\n- **Percent-encoding and backslashes**, JS `trim()` versus Python `strip()`, and `toLowerCase()` versus `lower()` differ as listed in the accepted limitations. None is in the fixture.\n- **Import side effects.** Loading `sync-whitelist.py` through importlib parses `schema.sql` at import time. If that file moves, the test errors on import rather than failing an assertion, which is at least loud.\n- **Merge conflicts.** The tracked `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict on merge. Take main's copy and re-run `validate_tests.py --compare`, as stated in the requirements.\n\n### Tradeoffs the operator is asked to accept\n\n- **Parity is proven only for fixture inputs.** Parity on other inputs is best effort from `urlparse` + `ipaddress` + `idna`. The upgrade path is to add inputs to the fixture.\n- **The test suite gains a hard dependency on `node` and a current `dist`.** When either is missing the test fails rather than skips, as required.\n- **The helper sits next to a similarly named `normalize_host` with different behaviour.** The two are told apart only by name and docstring.\n- **Branch 4 stores `@`, `?`, `#` and port suffixes as given, and existing rows are not rewritten.** The first updater run after the change may treat an old spelling and its new spelling as different hosts. Both points are already accepted in the requirements.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impact path=\"engine/server/data/moderation.py\" element=\"new normalize_host_token() and its private hostname step, placed after normalize_host (lines 39-63); module imports (lines 14-18); header comment (lines 5-11)\">\n**What changes.** A new public `normalize_host_token(value: str) -> str | None` goes directly after `normalize_host`, with one private helper that turns `urlparse` output into what WHATWG `URL.hostname` would give. The imports gain stdlib `ipaddress`. `urlparse` is already imported (line 18) and `from __future__ import annotations` is at line 3. Any constants go at module level. The header comment's \"host normalization\" bullet (line 9) may name both normalisers so the split is visible.\n\nDocstring style in this file is one-line and descriptive (e.g. line 40, `\"\"\"Normalize host input (lower, strip protocol/path, trim dots/spaces).\"\"\"`), with `\"\"\"Handle ...\"\"\"` on private helpers (lines 323, 340). The new docstring must say the function is an exact port of the crawler's `normalizeHostToken` and differs from `normalize_host`.\n\nReference behaviour, checked against `engine/crawler/src/host-filters.ts:83-100`:\n- `raw = value.trim().toLowerCase()`; empty \u2192 null\n- starts with `http://` or `https://` \u2192 `new URL(raw).hostname.toLowerCase() || null`\n- contains `/` \u2192 `new URL(\"https://\" + raw).hostname.toLowerCase() || null`\n- otherwise `raw.replace(/^\\.+|\\.+$/g, \"\") || null`\n- the whole body is inside try/catch \u2192 null\n\n**What depends on it.**\n- The two job call sites (entries below) and the new test.\n- The module is imported at Engine startup (`engine/server/api/server.py:97`) and by `engine/server/data/serving_moderation.py:11`.\n- It is also imported by `instance-denylist-cli.py:21`, `channel-moderation-cli.py:23`, `compare-join-hosts.py:23`, `sync-whitelist.py:26`, `updater-worker.py:27` and `jobs/tests/test-moderation-integration.py:31`. A syntax or import error here therefore takes down the Engine and every job, not just the two callers.\n\n**Regression risk: medium.** Adding a function changes no existing caller, but getting parity right has pitfalls:\n1. `urlparse('https://[::1]:8080/').hostname` gives `::1`, so the brackets must be put back. Only a host containing `:` is treated as IPv6, because `.hostname` never keeps the port.\n2. Non-ASCII hosts go through `.encode(\"idna\").decode(\"ascii\")`. That raises UnicodeError (a ValueError subclass) on invalid labels, and it must be caught. ASCII hosts must NOT go through the codec, because it rejects empty or over-63-character labels that WHATWG accepts.\n3. `.port` raises ValueError for a non-numeric port or one above 65535, so it must be read inside the try.\n4. `urlsplit` behaviour varies with the CPython version: bracketed-host validation and stripping of leading C0 characters and spaces changed in 3.11.4/3.12. Parity is proven only on the interpreter that runs the test, which may not be the job runtime (docs use `./venv/bin/python3`).\n5. `ipaddress.IPv6Address` accepts scope ids (`fe80::1%eth0`) that WHATWG rejects. This is outside the fixture and accepted.\n6. Branch 4 strips only `.` (`str.strip(\".\")`) after the initial strip/lower and never calls the parser.\n7. The WHATWG hostname returned by branches 2 and 3 keeps a leading or trailing dot (`https://tube.example./` \u2192 `tube.example.`), and so does `urlparse`. The port must NOT strip it. Stripping would break exact parity (see the host-filters read-back entry).\n\nThe Engine imports this module at startup, so the new code must do no module-level work beyond defining constants.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"normalize_host() (lines 39-63), unchanged, and its callers purge_host_data (162), purge_similarity_for_host (199), collect_similarity_host_stats (250), _row_host (414)\">\n**What changes.** Nothing. The requirements forbid touching it.\n\n**What depends on it.**\n- The denylist and channel CLIs (`instance-denylist-cli.py:145`, `channel-moderation-cli.py:78`).\n- The updater's stale-host purge: `updater-worker.purge_hosts` (lines 484-516) passes each stale host to `purge_host_data` / `purge_similarity_for_host`, which re-normalise it through `normalize_host` before `DELETE ... WHERE host = ?`.\n- Serving-time filtering (`_row_host`).\n\n**Regression risk: low, but there is an interaction to record.** Join hosts now use the crawler's spelling (`[::1]`, `xn--...`). `normalize_host` returns IPv6 without brackets and does no punycode conversion. A stale `[::1]` would therefore be purged as `::1` and match no rows, and a denylist entry typed as a unicode IDN never matches the punycode join host. Both are pre-existing and accepted as known limitations. The two functions now sit side by side with different contracts; the new docstring is what stops a later reader from merging them.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"module-level import `from data.moderation import ensure_moderation_schema, list_active_denied_hosts` (line 26)\">\n**What changes.** `normalize_host_token` is added to this single-line import.\n\n**What depends on it.** The whole module. The import sits after the `sys.path` setup (lines 16-22), which puts `engine/server` and `engine/server/api` at `sys.path[0]`.\n\n**Regression risk: low.** A misspelt name raises ImportError at load, which the new test's importlib load and any run of the job both catch.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"fetch_hosts() (lines 219-250), the line `host_value = str(host).strip().lower()` (243)\">\n**What changes.** Line 243 becomes `host_value = normalize_host_token(str(host))`. The `if host_value:` guard on line 244 already skips None. Everything else stays the same:\n- the User-Agent `peertube-graph-whitelist-sync/1.0`\n- `(HTTPError, URLError)` \u2192 RuntimeError\n- the payload shapes (a dict with `\"data\"`, or a list; `entry.get(\"host\")` for dicts)\n- `ValueError(\"Unexpected whitelist JSON shape.\")`\n- `ValueError(\"Whitelist contained no hosts.\")` when no entry survives\n\n**What depends on it.**\n- `main()` line 571 feeds `remote_hosts` into the rest of the job:\n  - include mode: `selected_hosts_before_deny = remote_hosts` (609)\n  - exclude mode: `source_hosts - remote_hosts` (607), where `source_hosts` comes from `source.videos.instance_domain` and is therefore crawler-normalised\n  - `- denylisted_hosts` (610-612)\n  - `sync_hosts` (640)\n  - `rebuild_content_tables` (641), which copies channels, videos and embeddings `WHERE instance_domain IN (hosts)`\n- The new test calls it directly with a `file://` URL. `urlopen` accepts a `Request` for `file:`, and the timeout has no effect there.\n\n**Regression risk: medium in behaviour, low in code.**\n- Entries that used to keep a non-crawler spelling now match the crawl DB. In include mode `rebuild_content_tables` may copy more rows for them; in exclude mode fewer hosts show up as falsely \"missing\".\n- `sync_hosts` (lines 420-445) deletes every `instances.host` row not in the new set. On the first run, old-spelling rows in `whitelist.db` are therefore replaced wholesale.\n- If every entry normalises to None, the job still raises \"Whitelist contained no hosts.\", as the requirements require.\n- `str(host)` on a truthy non-string entry (dict or bool) differs from the crawler's `extractWhitelistHost` (`crawler.ts:290-304`, which accepts only strings and numbers). This predates the build and is out of scope.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"module top level: sys.path mutation (16-22), imports of scripts.cli_format and server_config (24-25), INSTANCE_/CHANNEL_/VIDEO_COLUMNS parsed from engine/crawler/schema.sql at import (36, 92-96), __main__ guard (676)\">\n**What changes.** Nothing. This matters only because the new test loads the file through `importlib.util.spec_from_file_location`. The filename is hyphenated, so the spec needs an identifier-like module name.\n\n**What depends on it.**\n- The load works only if `engine/crawler/schema.sql` has the `instances`, `channels` and `videos` `CREATE TABLE IF NOT EXISTS` blocks.\n- It also needs `engine/server/scripts/cli_format.py` and `engine/server/api/server_config.py`.\n- `main()` runs only under `if __name__ == \"__main__\"` (line 676), so loading starts no job.\n\n**Regression risk: low.**\n- Loading leaves `engine/server` and `engine/server/api` on `sys.path` for the rest of the pytest session.\n- `engine/server/api/server.py` has the same module name, `server`, as `client/backend/server.py`, which `tests/active/conftest.py` imports first. `sys.modules` keeps the Client module, so later imports stay safe, but only because of that ordering.\n- If `schema.sql` moves, the test errors at import. That is a loud failure.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"sync_hosts() (lines 420-445) and ensure_whitelist_schema() (253-267), used by the new test\">\n**What changes.** Nothing.\n\n**What depends on it.** The new acceptance test stores the fetched set through `ensure_whitelist_schema` and `sync_hosts` into a temporary SQLite file.\n\n**Regression risk: low.** `sync_hosts` is annotated `tuple[int, int]` but returns a 3-tuple `(total, removed, added)` (line 445). The test must not unpack it as a pair. It also needs a plain connection, since there is no `row_factory` requirement here. It must never open the shared `engine/server/db/whitelist.db`.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"module-level parenthesised import `from data.moderation import (...)` (lines 27-32)\">\n**What changes.** `normalize_host_token,` is added in alphabetical position, between `list_active_denied_hosts` and `purge_host_data`, since the existing list is sorted.\n\n**What depends on it.** The whole module.\n\n**Regression risk: low.** An import error would show up at the new test's importlib load.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"fetch_join_hosts() (lines 414-441), the line `value = str(host).strip().lower()` (438)\">\n**What changes.** Line 438 becomes `value = normalize_host_token(str(host))`. The `if value:` guard on line 439 skips None. Everything else stays the same:\n- the User-Agent `peertube-browser-updater/1.0`\n- the RuntimeError `Failed to fetch hosts from ...`\n- the payload shapes\n- `ValueError(\"Unexpected whitelist JSON shape.\")`\n- unlike `fetch_hosts`, it still does not raise on an empty set (an existing asymmetry, kept)\n\n**What depends on it.** `main()` lines 829-872, under `--sync-join-whitelist`:\n- `effective_join_hosts = join_hosts - denied_hosts` (831)\n- `sync_stale_hosts = prod_hosts - effective_join_hosts` (833)\n- `sync_new_hosts = effective_join_hosts - prod_hosts` (834)\n- the stale hosts go to `purge_hosts(...)`: a dry-run plan first, then real deletes from the prod and similarity DBs when `--yes` is passed (843-872)\n- `sync_new_hosts` is written by `write_hosts_file` (line 893) and handed to the crawler as `--whitelist-file` (915), where `loadHostsFromFile` re-normalises it (see the host-filters read-back entry)\n- the orchestrator smoke test drives this function end-to-end, and the new test calls it directly with a `file://` URL\n\n**Correction to the earlier inventory.** The earlier entry said the Python output is always a fixed point of `normalizeHostToken`. That is false. Plain hosts, `[::1]` and `xn--...` do pass through branch 4 unchanged. But a branch-2/3 result with a leading or trailing dot (`https://tube.example./` \u2192 `tube.example.`, matching WHATWG and the crawler's URL mode) is stripped to `tube.example` when the crawler reads the hosts file back.\n\n**Regression risk: medium-high, because this set feeds a destructive purge.**\n- Suppose the port returns None or a different spelling for an entry the crawler normalises to host H. Then H, already in prod, lands in `sync_stale_hosts`, and with `--yes` its instances, channels, videos, embeddings and similarity rows are deleted.\n- Before this change, that already happened for any entry with a scheme, a path or trailing dots. After it, only parity gaps can cause it: IDNA 2003 vs UTS #46, a `.port` ValueError on input WHATWG accepts, or a `urlsplit` difference between Python versions. The net effect should be fewer false stale hosts, but a bug in the helper is a data-loss path, not a cosmetic mismatch.\n- On the first run after the change, prod rows stored under an old non-crawler spelling become stale and are purged. This is accepted; it needs `--yes`, and `--dry-run` shows the plan.\n- The dotted-URL churn described in the read-back entry predates this build and is not a regression.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"write_hosts_file() (lines 465-481) and its two callers (888 exclude file, 893 whitelist file \u2192 --whitelist-file at 915)\">\n**What changes.** Nothing in the code. What it writes changes: `sync_new_hosts` now holds `normalize_host_token` output, one host per line, sorted, UTF-8.\n\n**What depends on it.** The crawler's `instances-cli --whitelist-file` \u2192 `crawler.ts:24-25` \u2192 `loadHostsFromFile`, which trims each line, skips blanks and `#` lines, and runs `normalizeHostToken` again.\n\n**Regression risk: low.** For almost every value the second normalisation changes nothing. The one exception is a URL-form entry whose host has a leading or trailing dot, which becomes a different string in prod than in the join set (see the read-back entry). A host starting with `#` would be dropped as a comment. That can only come from branch 4, which keeps `#`, it predates this build, and it is accepted.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"list_prod_hosts() (lines 444-451) and load_denied_hosts() (454-462), unchanged\">\n**What changes.** Nothing. `list_prod_hosts` keeps `str(row[0]).strip().lower()` by explicit decision.\n\n**What depends on it.** It is the other side of the stale/new set differences in `main()` (lines 831-834).\n\n**Regression risk: low.**\n- Prod `instances.host` rows are written by the crawler, so strip/lower is the identity on normal rows. A row written earlier by Python with dots or a scheme would show up as stale; that falls under the \"existing rows not rewritten\" limitation.\n- The denied hosts come from `list_active_denied_hosts` (rows stored via `normalize_host`), so IDN and IPv6 denylist entries may not match the new spelling. This is accepted.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"module top level (lines 1-33) and __main__ guard (1161)\">\n**What changes.** Nothing beyond the import.\n\n**What depends on it.** The new test's importlib load. The top level only:\n- mutates `sys.path` (adding `engine/server`)\n- imports stdlib modules, `scripts.cli_format` and `data.moderation`\n\n`server_config` is imported lazily inside `parse_args` (lines 85-89), and `resolve_default_engine_service_name`, which runs bash, is only reached from `parse_args`/`main`.\n\n**Regression risk: low.** A correction to the plan: this module does NOT parse `schema.sql` at import (it does so only inside `main`, line 788). Only `sync-whitelist.py` does.\n</impact>\n<impact path=\"engine/crawler/src/host-filters.ts\" element=\"normalizeHostToken() (lines 83-100), the reference implementation, unchanged\">\n**What changes.** Nothing. Changing crawler behaviour is out of scope.\n\n**What depends on it.**\n- `crawler.ts:8, 258, 353`: `fetchWhitelistHosts` \u2192 `parseHostString` \u2192 `normalizeHostToken`.\n- `loadHostsFromFile` (see the next entry).\n- The new fixture pins its output. If this function is edited without rebuilding `dist`, or edited so that a fixture result changes, the new test fails.\n\n**Regression risk: none from this build.** It is the oracle. Its docstring, \"Handle normalize host token.\", is not touched.\n</impact>\n<impact path=\"engine/crawler/src/host-filters.ts\" element=\"loadHostsFromFile() (lines 10-22): re-normalisation of the updater's --whitelist-file (the read-back)\">\n**What changes.** Nothing in the file. This entry records a behaviour the earlier inventory got wrong.\n\n**What depends on it.** `crawler.ts:25` (whitelist file) and `crawler.ts:27` (exclude file). It is also used as the exclude-hosts reader by `channels-worker.ts:74, 108`, `videos-worker.ts:150, 209, 234` and `channels-videos-count-worker.ts:44`.\n\n**The read-back is not always an identity.** Each line goes through `normalizeHostToken`, and a bare host takes branch 4, which strips leading and trailing dots (line 96). The updater writes `normalize_host_token` output, which for URL-form entries is a WHATWG hostname that may end in a dot. Worked through:\n- JoinPeerTube entry `https://tube.example./` \u2192 Python and the crawler's URL mode give `tube.example.`\n- the file-mode crawl stores `tube.example`\n- the next `--sync-join-whitelist` run finds prod `tube.example` missing from the join set \u2192 it is marked stale (purged with `--yes`) and recrawled\n\nPython and the crawler still agree on the value, which is the requirement. The churn existed before this change under a different spelling (the old strip/lower kept `https://tube.example./` as-is), so it is not a regression. None of the 14 pinned inputs is affected.\n\n**Regression risk: low.** Fixing it means making the crawler's file mode and URL mode agree. That is a crawler change and out of scope; it is recorded for the roadmap.\n</impact>\n<impact path=\"engine/crawler/dist/host-filters.js\" element=\"compiled normalizeHostToken (lines 81-99), run by the new test through node\">\n**What changes.** Nothing is written. The new test imports it with `node --input-type=module` via a `file://` URL.\n\n**Checked:**\n- Its only import is `node:fs` (line 4), so no `node_modules` is needed.\n- The body matches `src/host-filters.ts:83-100` line for line.\n- No ignore rule excludes it: the root `.gitignore` ignores `node_modules/` and `engine/.gitignore` ignores only `.pixi/*`.\n\n**What depends on it.** The Node half of the parity test. `engine/crawler/test-url-safety.mjs:7` already imports `./dist/host-filters.js` directly, which is the precedent.\n\n**Regression risk: medium, for the suite rather than production.**\n- The \"dist is stale\" rule decides whether a clean tree goes red. An mtime-only rule can false-fail after a checkout.\n- The git-based rule needs `git` on PATH. This is a linked worktree, where `.git` is a file; `git log -1 --format=%ct -- <path>` still works there.\n- Failure modes such as git missing, a shallow clone, or untracked files must fail loudly, never skip.\n- The build checkpoint must settle the rule.\n</impact>\n<impact path=\"engine/crawler/package.json\" element=\"`&quot;type&quot;: &quot;module&quot;` (line 4) and the build script (line 8: `node node_modules/typescript/bin/tsc -p tsconfig.json`)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- `\"type\": \"module\"` is why `dist/*.js` loads as ESM.\n- The fail-loud message should name the fix: `cd engine/crawler && npm install && npm run build`.\n\n**Regression risk: low.** A build-first variant would need `node_modules/typescript`, which a fresh worktree lacks. That supports fail-loudly.\n</impact>\n<impact path=\"engine/crawler/src/crawler.ts\" element=\"crawl() whitelist source (lines 23-36), fetchWhitelistHosts() (246-269), extractWhitelistEntries() (274-285), extractWhitelistHost() (290-304), parseHost() (334-347), parseHostString() (352-354)\">\n**What changes.** Nothing. This is the crawler's own reader of the same payload, the behaviour the Python readers must match.\n\n**What depends on it.** `instances-cli`, which the updater runs with `--whitelist-file` (or `--whitelist-url`).\n\n**Regression risk: none from this build.** Differences outside the port stay as they are:\n- The crawler accepts only string or number hosts and trims before normalising; Python calls `str(host)` on any truthy value.\n- The crawler raises `Unexpected whitelist JSON shape.` for a dict whose `data` is not an array; Python accepts `\"data\" in payload` whatever its type.\n- `parseHost` returns `ref.host.toLowerCase()` without normalising (line 340).\n</impact>\n<impact path=\"engine/server/db/jobs/compare-join-hosts.py\" element=\"hosts_from_payload() (line 80) and load_local_hosts() (line 96), both `str(...).strip().lower()`\">\n**What changes.** Nothing. Explicitly out of scope.\n\n**What depends on it.** The operator diagnostic that compares JoinPeerTube hosts with the local `instances` table.\n\n**Regression risk: low, but it drifts.** After this build it is the only Python reader of the list that still uses strip/lower. It can report hosts as \"missing\" (`https://x/` vs `x`) that the jobs now treat as present. This is a roadmap follow-up.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"load_hosts_from_json() (lines ~347-382, own strip/lower at 375), start_whitelist_server() (~396-408), run_orchestrator() (411-450), payload build (964-985)\">\n**What changes.** Nothing in the file. It must still pass.\n\n**Correction to the plan.** The smoke test does NOT go through `fetch_hosts`. It writes `whitelist.json` (`{\"total\", \"data\": [{\"host\": ...}]}`), serves it with `python -m http.server`, and runs `updater-worker.py --whitelist-url` (lines 419-441). That exercises `fetch_join_hosts`.\n\nThe hosts come from `engine/server/db/jobs/tests/test-instances.json` (per `ORCHESTRATOR_SMOKE_TEST.md:42`) or from prod rows, which are plain crawler-normalised hosts that pass through the helper unchanged. Its expectations therefore hold.\n\n**Regression risk: low for correctness.** Running it needs node, a built `dist`, the embedding stack and network access. That limits whether it can be run here, but it is not a regression.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-moderation-integration.py\" element=\"standalone script importing data.moderation (lines 31-38)\">\n**What changes.** Nothing. It must still pass.\n\n**What depends on it.** It imports `ensure_moderation_schema`, `list_active_denied_hosts`, `normalize_host`, `now_ms`, `purge_host_data` and `purge_similarity_for_host`, plus `data.serving_moderation`. It does not import either job. Its own strip/lower calls (lines 484, 947, 1030) are local set arithmetic.\n\n**Regression risk: low.** It can break only if the `moderation.py` edit fails to import or alters `normalize_host`. It is run separately from `validate_tests.py`.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"startup import `from data.moderation import ensure_moderation_schema` (line 97)\">\n**What changes.** Nothing in the file. The module it imports gains a function and an `ipaddress` import.\n\n**What depends on it.** The Engine process, and so every Engine-backed test through the `engine` fixture in `conftest.py`.\n\n**Regression risk: very low.** Only an import-time failure of `moderation.py` matters, and it would stop the Engine from starting.\n</impact>\n<impact path=\"engine/server/data/serving_moderation.py\" element=\"`from data.moderation import ModerationFilterStats, filter_rows_by_moderation` (line 11)\">\n**What changes.** Nothing.\n\n**What depends on it.** Serving-time moderation in the Engine and in the integration script.\n\n**Regression risk: very low.** It is affected only by an import-time failure of `moderation.py`.\n</impact>\n<impact path=\"engine/server/db/jobs/instance-denylist-cli.py\" element=\"normalize_host usage (import at line 21, call at 145)\">\n**What changes.** Nothing. Out of scope.\n\n**What depends on it.** The operator's denylist entries, which feed `list_active_denied_hosts`. Both jobs subtract that set from the normalised join set.\n\n**Regression risk: low.** IDN and IPv6 entries are stored in unicode or without brackets, so they may not match the new crawler-style spelling. This predates the build and is accepted.\n</impact>\n<impact path=\"engine/server/db/jobs/channel-moderation-cli.py\" element=\"normalize_host usage (import at line 23, call at 78)\">\n**What changes.** Nothing. Out of scope.\n\n**What depends on it.** `channel_moderation.instance_domain` rows, which serving-time filtering compares with `normalize_host(row host)`.\n\n**Regression risk: none from this build.** It never reads the output of `normalize_host_token`.\n</impact>\n<impact path=\"engine/crawler/schema.sql\" element=\"instances/channels/videos CREATE TABLE blocks, parsed at import by sync-whitelist.py\">\n**What changes.** Nothing.\n\n**What depends on it.** `sync-whitelist.py` (lines 36 and 92-96) parses these blocks at import, so the new test's importlib load depends on this file.\n\n**Regression risk: low.** If it moves or changes, the test errors loudly.\n</impact>\n<impact path=\"tests/active/test_host_normalisation.py\" element=\"new pytest file (working name)\">\n**What changes.** A new file.\n- It puts `engine/server` on `sys.path` the way `test_db.py:22-26` and `test_random_videos.py:19-24` do (a `SERVER_DIR` constant, `sys.path.insert(0, ...)`, `# noqa: E402` imports), then imports `normalize_host_token` from `data.moderation`.\n- **Part 1:** a test parametrised over the fixture pairs.\n- **Part 2:** one `node --input-type=module` subprocess.\n  - Before it runs, `pytest.fail` with a message naming the fix if `shutil.which(\"node\")` finds nothing, if `dist/host-filters.js` is missing, or if `dist` is stale.\n  - The inline script reads the fixture inputs as JSON on stdin and imports the `dist` module by `file://` URL.\n  - The existing precedents (`test_frontend_*.py`) call `\"node\"` without a which-check.\n- **Part 3:** the job tests.\n  - Load both jobs with `importlib.util.spec_from_file_location` (precedent: `test_similar.py:36-41`).\n  - Serve a `file://` payload from `tmp_path`.\n  - `fetch_hosts` returns `{\"tube.example\"}`, which is then stored through `ensure_whitelist_schema` + `sync_hosts` into a temp DB (3-tuple return).\n  - A mixed-invalid, dict-shape payload asserts `fetch_join_hosts == fetch_hosts`.\n\n**What depends on it.** `validate_tests.groups()` picks it up automatically (`tests/active/test_*.py`). It is unmapped until harvest, so it runs on every invocation. It uses no Engine fixture, but pytest still imports `conftest.py`, which imports the Client backend.\n\n**Regression risk: low for production, medium for suite stability.**\n- The node and staleness gates are the likely source of false reds.\n- The module docstring should follow the suite's style: a summary line, then bullets for each claim, as in `test_similar.py:1-18` and `test_db.py:1-8`.\n- It must never touch `engine/server/db/whitelist.db`, which is shared across worktrees.\n- It must not request the `engine`, `engine_client`, `unpublished_client` or `dataset` fixtures.\n</impact>\n<impact path=\"tests/active/host_tokens.json\" element=\"new JSON fixture of {input, expected} pairs (14 pinned values, null for None)\">\n**What changes.** A new file holding the pinned pairs. It includes `\"https://b\u00fccher.example/\"`, so it must be read with `encoding=\"utf-8\"`, and the node subprocess needs `text=True, encoding=\"utf-8\"`. Otherwise a non-UTF-8 locale corrupts the `\u00fc`.\n\nOptional extra pair from step 4: `\"https://tube.example./\"` \u2192 `\"tube.example.\"`. It pins the dot-keeping URL behaviour on both sides. WHATWG, `urlparse` and the crawler all agree on it, so it adds no failure mode. Leave it out if the set must stay at exactly the 14 required values.\n\n**What depends on it.** Both halves of the parity test.\n\n**Regression risk: low.** It is not a `test_*.py` file, so it is not a group. At harvest the `test_groups` entry must list it, or an edit to the fixture alone will not re-run the test.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"module-level imports (lines 29-41: client/backend inserted at sys.path[0], `import server`, `lib.*`); Engine fixtures\">\n**What changes.** Nothing.\n\n**What depends on it.** Every test in `tests/active`, including the new one.\n\n**Regression risk: low.** The job loads put `engine/server/api` (which holds `server.py`, `http_utils.py`, `server_config.py`) on `sys.path`. By then conftest has already cached the Client's `server` and `lib` in `sys.modules`. `client/backend` holds only `server.py` and `lib/`, so `data`, `scripts` and `server_config` resolve to the Engine copies. The new test leaves `sys.path` mutated, the same as existing tests do.\n</impact>\n<impact path=\"tests/active/test_frontend_videos.py\" element=\"node invocation precedent (line 66); also test_frontend_blocks.py:79, test_frontend_profile.py:70, test_frontend_reactions.py:134/145\">\n**What changes.** Nothing.\n\n**What depends on it.** These tests already need `node` on the PATH that pytest sees, so the suite already goes red without node. The new hard dependency is consistent with that.\n\n**Regression risk: none.** Listed so the new test's node call and its message follow the existing convention.\n</impact>\n<impact path=\"engine/crawler/test-url-safety.mjs\" element=\"standalone node harness importing ./dist/host-filters.js (line 7)\">\n**What changes.** Nothing.\n\n**What depends on it.** Nothing automated: it is run by hand, as is `test-text-limits.mjs`.\n\n**Regression risk: none.** It shows that `dist/host-filters.js` loads under plain node with no `node_modules`.\n</impact>\n<impact path=\".un/skills/devsecops/scripts/validate_tests.py\" element=\"groups() (584-613), claimed()/digest (616-677), runner() (498-518)\">\n**What changes.** Nothing.\n\n**What depends on it.** The suite run that must stay green:\n- `groups()` discovers the new `test_*.py`, and an unmapped group always runs.\n- `claimed()` digests only the test file plus its mapped files, so the fixture is covered only once it is mapped.\n- `runner()` uses `pixi run --manifest-path` only if `pixi.toml` or `pixienv/pixi.toml` exists. Neither exists in this worktree (checked the root and `engine/`), so it uses `sys.executable`.\n\n**Regression risk: low.** The Python version that proves parity depends on this runner and may differ from the job runtime.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups map (lines 14-88)\">\n**What changes.** Nothing in this worktree. The entry is added at harvest on main. It should map `test_host_normalisation.py` to:\n- `engine/server/data/moderation.py`\n- `engine/server/db/jobs/sync-whitelist.py`\n- `engine/server/db/jobs/updater-worker.py`\n- `engine/crawler/src/host-filters.ts`\n- `engine/crawler/dist/host-filters.js`\n- `tests/active/host_tokens.json`\n\n**What depends on it.** Stale-group selection.\n\n**Regression risk: low.** An entry that lists too few files misses re-runs. Also, `.un/` is in the root `.gitignore`, so this config is local and not versioned.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked suite record\">\n**What changes.** It is rewritten by the post-build `validate_tests.py` run.\n\n**What depends on it.** The comparison against the baseline (green: code 0, variant false).\n\n**Regression risk: none functionally.** It will conflict on merge: take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n</impact>\n<impact path=\"tests/last_test_output.txt\" element=\"tracked captured pytest output\">\n**What changes.** It is rewritten by the post-build run.\n\n**What depends on it.** Nothing in code.\n\n**Regression risk: none.** Resolve its merge conflict the same way as `last_test_validation.json`.\n</impact>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"DATA_BUILD.md\">\nSection \"2) Filter to JoinPeerTube whitelist\", Notes (lines 145-149): add one bullet. It should say that each whitelist entry is normalised the way the crawler normalises hosts (`data.moderation.normalize_host_token`, a port of `normalizeHostToken`):\n- URL-like entries lose the scheme, userinfo, port and path.\n- Bare entries lose leading and trailing dots.\n- Entries that normalise to nothing are skipped.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\">\n\"What Exactly Is Collected\" (line 59, \"Instances: from whitelist source\"): state that with `--sync-join-whitelist` the fetched hosts are normalised by the same crawler-equivalent rule before the new/stale/denylist comparison. State the one-time effect: rows stored under an older spelling show up as stale on the first run, so review them with `--dry-run` before `--yes`. The \"Important Flags\" list (lines 101-115) could also gain `--sync-join-whitelist`, `--yes` and `--dry-run`, which it currently omits.\n</doc>\n<doc path=\"docs/project/issues/06-normalise-instance-hosts.md\">\nAt harvest:\n- Tick the acceptance criteria.\n- Set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.\n- Record the accepted limitations: branch 4 keeps `@ ? #` and ports; parity is proven only for fixture inputs; `compare-join-hosts.py` still uses strip/lower; the file-mode read-back strips dots from URL-form hosts that end in a dot.\n</doc>\n<doc path=\"docs/project/plans/10-normalise-instance-hosts.md\">\nAt harvest: mark it delivered and point to `16-10-normalise-instance-hosts.md`. Note the corrections found in discovery:\n- The orchestrator smoke test exercises `fetch_join_hosts`, not `fetch_hosts`.\n- Only `sync-whitelist.py` parses `schema.sql` at import.\n- The updater's hosts file is not always left unchanged when the crawler reads it back (dotted URL-form hosts).\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nFollow-up entries, all out of scope for this build:\n- Move `compare-join-hosts.py` (`hosts_from_payload`, line 80) onto `normalize_host_token`.\n- Make the crawler's `--whitelist-file` mode (`loadHostsFromFile`, branch 4 strips dots) and its URL mode (keeps the WHATWG trailing dot) agree, so dotted entries stop churning through purge and recrawl.\n- Optionally, align `normalize_host` (denylist input) on bracketed IPv6 and punycode.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nengine/server/db/jobs/updater-worker.py fetch_join_hosts(): its output feeds `sync_stale_hosts = prod_hosts - effective_join_hosts`, and `purge_hosts` deletes those hosts from the prod and similarity DBs under `--yes`. Any parity gap where the port returns None or a different spelling than the crawler (IDNA 2003 vs UTS #46, a `.port` ValueError, a `urlsplit` difference between Python versions) turns a live instance into a purged one. The file-mode read-back also means that even exact parity can change the spelling of dotted URL-form hosts.\ntests/active/test_host_normalisation.py (the node and dist-staleness gate): because the test must fail rather than skip, a wrong staleness rule turns the suite red on clean trees. An mtime order after checkout is unreliable, and the git-based rule depends on git in a linked worktree. `node_modules/typescript` is absent, so a stale `dist` cannot be rebuilt in place.\nengine/server/data/moderation.py normalize_host_token(): the Engine imports this module at startup and so does every moderation CLI and job, and the new function sits beside `normalize_host`, which has a different contract. The IPv6 re-bracketing, the ASCII-only IDNA path, keeping the WHATWG trailing dot and the error catching must all be exact, and an import-time mistake takes down the Engine as well as both jobs.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the files it names: `moderation.py`, both jobs, `host-filters.ts` and its `dist` build, `package.json`, `crawler.ts`, the smoke test, `conftest.py`, the test precedents in `tests/active`, `validate_tests.py` and the `.gitignore` files. Every entry held up, including the corrections the inventory makes to the plan: the smoke test goes through `fetch_join_hosts`, not `fetch_hosts`; only `sync-whitelist.py` parses `schema.sql` when it is imported; `sync_hosts` returns 3 values; and the crawler's file read-back strips dots. The plan holds as written. The only issues I found are inside the helper and the test (how the Node script receives its input, and how IPv6 addresses are printed on different Python versions). Neither changes which files are touched, so they are recommendations, not new impacts.\n<question id=\"1\">\nYes. At `sync-whitelist.py:243` and `updater-worker.py:438` the helper call is a drop-in replacement for the current line, and the `if host_value:` / `if value:` guards that follow already skip None. `moderation.py` already imports `urlparse` (line 18) and has `from __future__ import annotations` (line 3), so the helper needs only `ipaddress` and the stdlib `idna` codec. I compared the four branches against `host-filters.ts:83-100`, and `dist/host-filters.js` imports only `node:fs`. The test plan is also feasible:\n- `urlopen` reads `file://` URLs.\n- Both jobs run `main()` only under a `__main__` guard, so loading them has no side effects.\n- The fixture can be read with `encoding=\"utf-8\"`.\n\nOne implementation detail matters: the Node script must be passed with `-e` (`--eval`) so that stdin stays free for the fixture inputs. See the recommendations.\n</question>\n<question id=\"2\">\n- **Both jobs now spell hosts the crawler's way.** In include mode, `rebuild_content_tables` may copy more rows for entries that used a non-crawler spelling before. In exclude mode, fewer hosts show up as falsely missing.\n- **One-time churn on the first run.** `whitelist.db` rows stored under an old spelling are replaced by `sync_hosts`. Prod rows stored under an old spelling become stale, and `purge_hosts` deletes them, but only with `--yes` (lines 856-872).\n- **A helper bug can delete data.** The updater's stale set feeds a destructive purge, so a helper that returns None or a different spelling for a valid entry can cause data loss.\n- **The test suite gains a hard dependency on `node` and an up-to-date `dist`.** The frontend tests already require node (`test_frontend_*.py`).\n- **Two normalisers with different rules now sit in the same module.** Denylist entries typed as IDN or IPv6 still don't match the join-host spelling. This was already true before and is an accepted limitation.\n- **Unchanged paths.** Outside `--sync-join-whitelist`, the updater still passes `--whitelist-url` to the crawler (line 917), which is unaffected.\n</question>\n<question id=\"3\">\nNothing beyond what the plan already does:\n- `normalize_host` and `list_prod_hosts` stay untouched.\n- The helper does no work at import time (the Engine imports this module at startup, `server.py:97`).\n- ValueError and UnicodeError are caught around the whole parse, including the `.port` read.\n- `test-moderation-integration.py` and `test-orchestrator-smoke.py` are run separately. `test-instances.json` contains no host with a scheme, path, uppercase letter or dot at either end, so the smoke test's hosts come through unchanged.\n- The full `validate_tests.py` run is compared against the green baseline.\n- At harvest, the `test_groups` entry lists the fixture and both `host-filters` files.\n- The merge conflicts in `tests/last_test_*` are resolved by taking main's copy and re-running `validate_tests.py --compare`.\n</question>\n<question id=\"4\">\n- **Stored values change.** `fetch_hosts` and `fetch_join_hosts` now return the crawler's `normalizeHostToken` result instead of `strip().lower()`. URL-form entries are stored as the bare hostname, IPv6 as `[..]`, IDNs as punycode.\n- **Invalid entries are dropped instead of stored:** `.`, `https://`, a bad port, bad IPv6, bad IDNA.\n- **Everything else is unchanged:** the error messages, the User-Agents, the accepted payload shapes, \"Whitelist contained no hosts.\", and the asymmetry where the updater does not raise on an empty set.\n- **`moderation.py` only gains a function.** No existing caller's behaviour changes.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Pass the Node script with `node --input-type=module -e <script>` and send the fixture inputs on stdin.** The script reads them with `fs.readFileSync(0, \"utf8\")`. `--input-type` applies only to `--eval` or stdin, so if the script itself is piped on stdin, the inputs have no channel left. Cost: none; it only settles how the inline script is invoked.\n\n2. **Name one more Python-version parity gap in the helper's accepted limitations.** Python 3.13 changed how IPv4-mapped IPv6 addresses are printed: `str(IPv6Address(\"::ffff:7f00:1\"))` now gives `::ffff:127.0.0.1`, while WHATWG gives `[::ffff:7f00:1]`. This belongs next to the existing `urlsplit` version risk in the `moderation.py` entry. Cost: one line of documentation. Closing the gap instead would cost a branch on `.ipv4_mapped` that formats the last 32 bits as two hex groups (about 3 lines). I recommend documenting it, not closing it: the input is not in the fixture, and closing it is speculative.\n\n3. **Settle the dist-staleness rule at the build checkpoint as the plan's git-based rule.** It needs `git` on PATH, and if git is missing or a file is untracked the test must fail loudly, not fall back silently. Cost: about 10 lines of subprocess code. It avoids false failures on a fresh clone, where an mtime-only rule would fail the test.\n\n4. **Add the optional `\"https://tube.example./\"` \u2192 `\"tube.example.\"` pair to the fixture only if the requirements allow more than the 14 required values.** It pins the dot-keeping URL behaviour that the read-back entry depends on. Cost: one fixture line, and no new ways for the test to fail.\n\n5. **Use `conftest.ROOT` to build paths in the new test,** as `test_similar.py:25` does, rather than recomputing the repository root. Cost: none.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/moderation.py` | adds `import ipaddress`, the constant `URL_SCHEME_PREFIXES`, `normalize_host_token()` and the private `_whatwg_hostname()` directly after `normalize_host`; the header bullet names both normalisers |\n| `engine/server/db/jobs/sync-whitelist.py` | line 26 import gains `normalize_host_token`; `fetch_hosts` line 243 swapped |\n| `engine/server/db/jobs/updater-worker.py` | the parenthesised import gains `normalize_host_token,` between `list_active_denied_hosts` and `purge_host_data`; `fetch_join_hosts` line 438 swapped |\n| `tests/active/host_tokens.json` | new, 15 `{input, expected}` pairs |\n| `tests/active/test_host_normalisation.py` | new, 5 tests: Python table, Node table, three job tests |\n| `DATA_BUILD.md`, `engine/server/db/jobs/docs/UPDATER_WORKER.md` | one note each (text below) |\n\nNo new file under `engine/`, no dependency, no new interface. The issue, plan and roadmap doc edits happen at harvest, as settled.\n\n## What the build needs to test\n\n1. `normalize_host_token` returns the pinned value for every fixture input. That covers all four branches, userinfo, port, IPv6 brackets, punycode, and the None cases.\n2. The crawler's compiled `normalizeHostToken` returns the same pinned values, so Python == crawler on the fixture.\n3. The test fails loudly when `node` is missing, `dist/host-filters.js` is missing, or `dist` is stale.\n4. `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` into `{\"tube.example\"}`, and `sync_hosts` stores that one row in a temporary DB.\n5. Entries that normalise to None are dropped, the fetch completes, and `fetch_join_hosts` == `fetch_hosts` on a dict-shape payload.\n6. `fetch_hosts` still raises `Whitelist contained no hosts.` when every entry normalises to None. This is existing behaviour the requirements restate, and it costs one assert.\n\n`test-moderation-integration.py`, `test-orchestrator-smoke.py` and `validate_tests.py` are run, not changed.\n\n## `engine/server/data/moderation.py`\n\nHeader comment, line 9:\n\n```python\n# - host normalization (normalize_host for operator input, normalize_host_token for hosts-list entries, a port of the crawler's normalizeHostToken),\n```\n\nImports, alphabetical in the existing block:\n\n```python\nimport ipaddress\nimport re\nimport sqlite3\nfrom dataclasses import dataclass\nfrom datetime import datetime, timezone\nfrom urllib.parse import urlparse\n```\n\nModule constant, placed after the imports and before `ModerationFilterStats`:\n\n```python\nURL_SCHEME_PREFIXES = (\"http://\", \"https://\")\n```\n\nNew code directly after `normalize_host`:\n\n```python\ndef normalize_host_token(value: str) -> str | None:\n    \"\"\"Normalize a hosts-list entry exactly as the crawler's normalizeHostToken (engine/crawler/src/host-filters.ts) does; unlike normalize_host, bare entries keep ports and URL entries yield the WHATWG hostname.\"\"\"\n    raw = value.strip().lower()\n    if not raw:\n        return None\n    try:\n        if raw.startswith(URL_SCHEME_PREFIXES):\n            return _whatwg_hostname(raw)\n        if \"/\" in raw:\n            return _whatwg_hostname(f\"https://{raw}\")\n        return raw.strip(\".\") or None\n    except ValueError:\n        return None\n\n\ndef _whatwg_hostname(url: str) -> str | None:\n    \"\"\"Handle the hostname WHATWG URL.hostname returns for url; raise ValueError where WHATWG throws.\"\"\"\n    parsed = urlparse(url)\n    # Reading .port raises ValueError on a non-numeric or out-of-range port, which WHATWG also rejects.\n    _ = parsed.port\n    host = parsed.hostname or \"\"\n    if not host:\n        return None\n    if \":\" in host:\n        return f\"[{ipaddress.IPv6Address(host).compressed}]\"\n    if not host.isascii():\n        host = host.encode(\"idna\").decode(\"ascii\")\n    return host.lower() or None\n```\n\nInvariants and decisions:\n- **Order.** The branch order and tests match `host-filters.ts:83-100` exactly. `raw.strip(\".\")` is `replace(/^\\.+|\\.+$/g, \"\")`. Branch 4 never parses, so `tube.example:9000`, `@`, `?`, `#` and non-ASCII characters pass through unchanged.\n- **One except.** A single `except ValueError` stands in for the crawler's whole-body try/catch. It also catches `UnicodeError` (idna), `ipaddress.AddressValueError`, urlsplit's `Invalid IPv6 URL`, and the `.port` error, because all of them subclass ValueError.\n- **IPv6.** It is detected by `\":\" in host`. `.hostname` never carries the port, so a colon can only come from an IPv6 literal. `.compressed` is the form WHATWG serialises, and the brackets are put back.\n- **IDNA only for non-ASCII.** Only non-ASCII hosts go through the `idna` codec. ASCII hosts skip it, so `a..b` and labels over 63 characters are kept, as WHATWG keeps them.\n- **Dots kept.** A trailing or leading dot in a URL-form host is kept (`https://tube.example./` \u2192 `tube.example.`), exactly as WHATWG keeps it. The fixture pins this.\n- **Nothing at import.** There is no module-level work beyond the tuple constant, because the Engine imports this module at startup.\n- **`normalize_host` untouched.**\n\n## Job call sites\n\n`sync-whitelist.py` line 26:\n\n```python\nfrom data.moderation import ensure_moderation_schema, list_active_denied_hosts, normalize_host_token\n```\n\n`fetch_hosts`, line 243 only:\n\n```python\n        host_value = normalize_host_token(str(host))\n```\n\n`updater-worker.py` import:\n\n```python\nfrom data.moderation import (\n    ensure_moderation_schema,\n    list_active_denied_hosts,\n    normalize_host_token,\n    purge_host_data,\n    purge_similarity_for_host,\n)\n```\n\n`fetch_join_hosts`, line 438 only:\n\n```python\n        value = normalize_host_token(str(host))\n```\n\nThe existing `if host_value:` / `if value:` guards already skip None. The User-Agents, error types and messages, payload-shape handling, the empty-set raise in `fetch_hosts` and the missing one in `fetch_join_hosts` are all unchanged. `list_prod_hosts` is untouched.\n\n## `tests/active/host_tokens.json`\n\n```json\n[\n  {\"input\": \" Tube.Example \", \"expected\": \"tube.example\"},\n  {\"input\": \"tube.example.\", \"expected\": \"tube.example\"},\n  {\"input\": \"..tube.example..\", \"expected\": \"tube.example\"},\n  {\"input\": \"https://Tube.Example/\", \"expected\": \"tube.example\"},\n  {\"input\": \"http://tube.example:8080/path\", \"expected\": \"tube.example\"},\n  {\"input\": \"https://user@tube.example\", \"expected\": \"tube.example\"},\n  {\"input\": \"tube.example/videos\", \"expected\": \"tube.example\"},\n  {\"input\": \"tube.example:9000\", \"expected\": \"tube.example:9000\"},\n  {\"input\": \"https://[::1]:8080/\", \"expected\": \"[::1]\"},\n  {\"input\": \"https://b\u00fccher.example/\", \"expected\": \"xn--bcher-kva.example\"},\n  {\"input\": \"\", \"expected\": null},\n  {\"input\": \"   \", \"expected\": null},\n  {\"input\": \".\", \"expected\": null},\n  {\"input\": \"https://\", \"expected\": null},\n  {\"input\": \"https://tube.example./\", \"expected\": \"tube.example.\"}\n]\n```\n\nThe file holds the 14 required pairs plus the optional dot-keeping pair from step 4. WHATWG, `urlparse` and the crawler all agree on that pair, and it guards against a later \"fix\" that strips the dot in the port. It is saved as UTF-8 (`\u00fc` written raw), and all inputs are unique, which the Node assertion relies on.\n\n## `tests/active/test_host_normalisation.py`\n\n```python\n\"\"\"The Engine's port of the crawler's host normalisation, and the two jobs that read the JoinPeerTube hosts list through it.\n\n- `data.moderation.normalize_host_token` returns the pinned value for every pair in `host_tokens.json`.\n- The crawler's compiled `normalizeHostToken` (`engine/crawler/dist/host-filters.js`, run under node) returns the same pinned values, so the Python port and the crawler agree on every fixture input. A missing node, a missing dist or a dist older than `src/host-filters.ts` fails the test, never skips it.\n- The whitelist sync job's host fetch turns `https://Tube.Example/` and `tube.example` into the single host `tube.example`, which `sync_hosts` stores as one row.\n- Entries that normalise to nothing are left out of both jobs' host sets, the fetch still completes, and the updater's join-host fetch returns the same set as the sync job's.\n\"\"\"\nfrom __future__ import annotations\n\nimport importlib.util\nimport json\nimport os\nimport shutil\nimport sqlite3\nimport subprocess\nimport sys\n\nimport pytest\nfrom conftest import ROOT\n\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nif str(SERVER_DIR) not in sys.path:\n    sys.path.insert(0, str(SERVER_DIR))\n\nfrom data.moderation import normalize_host_token  # noqa: E402\n\nJOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"\nCRAWLER_DIR = ROOT / \"engine\" / \"crawler\"\nSRC = CRAWLER_DIR / \"src\" / \"host-filters.ts\"\nDIST = CRAWLER_DIR / \"dist\" / \"host-filters.js\"\nBUILD_HINT = \"cd engine/crawler && npm install && npm run build\"\nFIXTURE = ROOT / \"tests\" / \"active\" / \"host_tokens.json\"\nPAIRS = json.loads(FIXTURE.read_text(encoding=\"utf-8\"))\n# Reads a JSON list of inputs on stdin and prints the crawler's normalizeHostToken of each.\nNODE_SCRIPT = \"\"\"\nimport { readFileSync } from \"node:fs\";\nconst { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);\nconst inputs = JSON.parse(readFileSync(0, \"utf8\"));\nprocess.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));\n\"\"\"\n\n\ndef _load_job(module_name: str, filename: str):\n    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)\n    module = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(module)\n    return module\n\n\n@pytest.fixture(scope=\"module\")\ndef jobs():\n    return _load_job(\"sync_whitelist_job\", \"sync-whitelist.py\"), _load_job(\"updater_worker_job\", \"updater-worker.py\")\n\n\ndef _payload_url(tmp_path, payload) -> str:\n    path = tmp_path / \"hosts.json\"\n    path.write_text(json.dumps(payload), encoding=\"utf-8\")\n    return path.as_uri()\n\n\ndef _commit_time(git: str, path) -> int | None:\n    out = subprocess.run([git, \"log\", \"-1\", \"--format=%ct\", \"--\", str(path)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()\n    return int(out) if out else None\n\n\ndef _dist_staleness() -> str | None:\n    \"\"\"Return why dist/host-filters.js is behind src/host-filters.ts, or None when it is current.\"\"\"\n    git = shutil.which(\"git\")\n    if git is None:\n        return \"git is not on PATH, so the freshness of dist/host-filters.js cannot be checked\"\n    src_dirty = subprocess.run([git, \"status\", \"--porcelain\", \"--\", str(SRC)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()\n    src_time = _commit_time(git, SRC)\n    dist_time = _commit_time(git, DIST)\n    # An uncommitted or untracked source is judged by mtime; committed files by commit time, which a checkout does not reorder.\n    if src_dirty or src_time is None or dist_time is None:\n        if DIST.stat().st_mtime < SRC.stat().st_mtime:\n            return \"dist/host-filters.js is older on disk than the edited src/host-filters.ts\"\n        return None\n    if src_time > dist_time:\n        return \"src/host-filters.ts was committed after dist/host-filters.js was last rebuilt and committed\"\n    return None\n\n\n@pytest.mark.parametrize(\"pair\", PAIRS, ids=[repr(pair[\"input\"]) for pair in PAIRS])\ndef test_python_port_returns_pinned_value(pair):\n    assert normalize_host_token(pair[\"input\"]) == pair[\"expected\"]\n\n\ndef test_crawler_dist_returns_pinned_values():\n    node = shutil.which(\"node\")\n    if node is None:\n        pytest.fail(f\"node is not on PATH; install Node.js, then run: {BUILD_HINT}\")\n    if not DIST.is_file():\n        pytest.fail(f\"{DIST} is missing; run: {BUILD_HINT}\")\n    stale = _dist_staleness()\n    if stale:\n        pytest.fail(f\"{stale}; run: {BUILD_HINT}\")\n    inputs = [pair[\"input\"] for pair in PAIRS]\n    proc = subprocess.run(\n        [node, \"--input-type=module\", \"-e\", NODE_SCRIPT], input=json.dumps(inputs), capture_output=True, text=True, encoding=\"utf-8\", timeout=60,\n        env={**os.environ, \"HOST_FILTERS_URL\": DIST.as_uri()},\n    )\n    assert proc.returncode == 0, proc.stderr\n    assert dict(zip(inputs, json.loads(proc.stdout))) == {pair[\"input\"]: pair[\"expected\"] for pair in PAIRS}\n\n\ndef test_sync_job_stores_one_spelling_per_host(jobs, tmp_path):\n    sync, _ = jobs\n    hosts = sync.fetch_hosts(_payload_url(tmp_path, [\"https://Tube.Example/\", \"tube.example\"]))\n    assert hosts == {\"tube.example\"}\n    conn = sqlite3.connect(tmp_path / \"whitelist.db\")\n    try:\n        sync.ensure_whitelist_schema(conn)\n        # sync_hosts returns (total, removed, added) despite its two-element annotation.\n        counts = sync.sync_hosts(conn, hosts)\n        conn.commit()\n        stored = [row[0] for row in conn.execute(f\"SELECT host FROM {sync.TABLE_NAME}\")]\n    finally:\n        conn.close()\n    assert counts == (1, 0, 1)\n    assert stored == [\"tube.example\"]\n\n\ndef test_jobs_drop_entries_that_normalise_to_nothing(jobs, tmp_path):\n    sync, updater = jobs\n    entries = [\"\", \"   \", \".\", \"https://\", \"https://Tube.Example/\", \"other.example.\"]\n    url = _payload_url(tmp_path, {\"data\": [{\"host\": entry} for entry in entries]})\n    expected = {\"tube.example\", \"other.example\"}\n    assert sync.fetch_hosts(url) == expected\n    assert updater.fetch_join_hosts(url) == expected\n\n\ndef test_sync_job_still_rejects_a_list_with_no_usable_host(jobs, tmp_path):\n    sync, _ = jobs\n    with pytest.raises(ValueError, match=\"Whitelist contained no hosts.\"):\n        sync.fetch_hosts(_payload_url(tmp_path, [\"   \", \".\", \"https://\"]))\n```\n\nSeams and decisions in the test:\n- **Fixture paths.** `ROOT` comes from `conftest`, as `test_similar.py` uses it. `SERVER_DIR` and the `# noqa: E402` import follow `test_db.py:22-26`. The file uses no Engine fixture, so it runs in the normal `validate_tests.py` pass.\n- **Loading the jobs.** Both are loaded through `spec_from_file_location` with identifier-like module names, following `test_similar.py:36-41`. Neither job defines a dataclass, so no `sys.modules` registration is needed. `main()` sits behind `__main__` guards. The module-scoped fixture loads each job once, and `sync-whitelist.py` parses `schema.sql` at that point, so if the file moves the tests error loudly.\n- **Payloads.** They are served as `file://` URIs from `tmp_path`. `urlopen` accepts a `Request` with headers for `file:` and ignores the timeout, so no server thread is needed. The mixed test uses the dict shape and the first test the list shape, so both shapes are covered. `\"\"` is dropped by the jobs' existing `if not host` before the helper runs; `\"   \"`, `\".\"` and `\"https://\"` reach the helper and return None.\n- **Temporary database.** Every database is a `tmp_path` file. The shared `engine/server/db/whitelist.db` is never opened.\n- **Node call.**\n  - It uses the absolute path from `shutil.which`.\n  - The dist URL is passed through the environment, which is `os.environ` plus one key, so PATH and the rest are kept.\n  - `encoding=\"utf-8\"` covers the raw `\u00fc` in stdout under non-UTF-8 locales. stdin is ASCII because `json.dumps` escapes by default.\n  - The zip into a dict makes a pytest failure show exactly which input differs.\n- **Staleness rule (recommended for the build checkpoint).**\n  - Committed files are compared by the last commit time of `src/host-filters.ts` versus `dist/host-filters.js`, which a fresh checkout's write order cannot disturb.\n  - An uncommitted or untracked source, or a path with no history (for example a shallow boundary or untracked `dist`), falls back to mtime.\n  - A missing `git`, or a git command that fails (`check=True` raises `CalledProcessError`), is a loud fail or error, never a skip.\n  - Ceiling: a commit that changes only a comment in `src` without recommitting `dist` reports stale. The fix, rebuild and commit, is cheap, and a false red is preferred to a silent pass.\n  - The alternative the checkpoint may pick instead is build-first. It is rejected because it needs `node_modules/typescript` and would write to the tree during a test run.\n\n## Documentation text\n\n`DATA_BUILD.md`, a new bullet appended to the \"Notes:\" list under section 2:\n\n```markdown\n- Each whitelist entry is normalised the way the crawler normalises hosts (`data.moderation.normalize_host_token`, a port of `normalizeHostToken`): URL-like entries lose the scheme, userinfo, port and path; bare entries lose leading and trailing dots; entries that normalise to nothing are skipped.\n```\n\n`UPDATER_WORKER.md`, line 59 becomes:\n\n```markdown\n- Instances: from whitelist source (JoinPeerTube URL by default). With `--sync-join-whitelist` the fetched hosts are normalised by the crawler-equivalent rule (`data.moderation.normalize_host_token`) before the new/stale/denylist comparison. Prod rows stored under an older spelling show up as stale on the first run after this change, so review the plan with `--dry-run` before passing `--yes`.\n```\n\nUnder \"Important Flags\", add `- \\`--sync-join-whitelist\\`, \\`--yes\\`, \\`--dry-run\\`` after `--whitelist-url`.\n\n## Verification commands (build step)\n\n1. `python -m pytest tests/active/test_host_normalisation.py -q` from the worktree root.\n2. `python engine/server/db/jobs/tests/test-moderation-integration.py`, then `test-orchestrator-smoke.py`. The smoke test drives `fetch_join_hosts` through `--whitelist-url`, not `fetch_hosts`, and needs node, a built `dist`, the embedding stack and network. If any of these is missing, report the run as not possible here rather than green.\n3. `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts`, compared against the green baseline (code 0, variant false).\n\n## Check against plan and requirements (pass 1: converged)\n\n- **Helper.** It lives in `moderation.py` after `normalize_host`, which is unchanged. It is stdlib only, adds one module constant and has a one-line docstring naming the port and the difference from `normalize_host`. All four branches are in order, and branch 4 does no parse and no punycode. Traced by hand, all 15 fixture pairs give the expected value through `urlparse` / `ipaddress` / `idna`.\n- **Jobs.** Only the one expression and the import change in each. `list_prod_hosts`, `compare-join-hosts.py`, the CLIs and the crawler are untouched.\n- **Acceptance criteria.**\n  - The Python table test and the Node test on `dist` share one fixture.\n  - Fail-loudly covers node, a missing dist and a stale dist, without depending on `node_modules`.\n  - The `https://Tube.Example/` + `tube.example` payload gives `{tube.example}`, stored via `sync_hosts` in a temp DB.\n  - None entries are dropped while the fetch completes.\n  - `fetch_join_hosts` == `fetch_hosts`.\n  - The empty-set raise is kept.\n- **Style.** One statement per line, no softwrap, `from __future__ import annotations` in both touched Python modules that already use it, no new dependency, no single-implementation interface.\n- **Deliberate simplifications, each with its ceiling and upgrade path.**\n  - Parity is proven only on the fixture and on the interpreter that runs pytest. The upgrade is to add fixture inputs.\n  - There is no forbidden-host-code-point check. Upgrade: one module constant plus one test in `_whatwg_hostname`, the first time a fixture input exposes the gap.\n  - IPv6 scope ids are accepted and IDNA 2003 is used, as the settled limitations state.\n\nNothing is left unresolved that needs the operator. The staleness rule remains for the build checkpoint to settle, as the requirements say.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the pure function `data.moderation.normalize_host_token`, called directly from pytest with `engine/server` added to sys.path, following test_db.py:22-26 (`SERVER_DIR` insert plus a `# noqa: E402` import) and `ROOT` from conftest as test_similar.py uses it. The test is parametrised over the pairs loaded at run time from `tests/active/host_tokens.json` (15 pairs, with ids from repr(input)). It asserts `normalize_host_token(input) == expected`, with JSON null standing for None. Together the pairs exercise all four branches, userinfo, port drop, port keep in branch 4, IPv6 re-bracketing, punycode, the None cases and dot keeping in URL form. It runs in the normal validate_tests.py pass because it uses no Engine fixture.</checkpoint>\n<name>Python port of normalizeHostToken</name>\n<intent>`engine/server/data/moderation.py` gains `normalize_host_token`, placed directly after the unchanged `normalize_host`, and it returns the pinned value for every pair in `tests/active/host_tokens.json`.</intent>\n<clause_1>`normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null.</clause_1>\n<files>engine/server/data/moderation.py (EDITED), tests/active/host_tokens.json (NEW), tests/active/test_host_normalisation.py (NEW)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam, clause 1: the crawler's compiled module `engine/crawler/dist/host-filters.js`, entered by one `node --input-type=module -e` subprocess. The subprocess imports that module by its file:// URL (passed in the HOST_FILTERS_URL env var), reads the fixture inputs as JSON on stdin and prints `normalizeHostToken` of each as JSON. The test asserts returncode 0 and that dict(zip(inputs, outputs)) equals the pinned {input: expected} map. Because phase 1 checks Python against the same map, passing this proves Python == crawler on the fixture. Seam, clause 2: the pytest outcome of the node test itself. The checkpoint runs `python -m pytest tests/active/test_host_normalisation.py -k crawler_dist` in a subprocess three times: with a PATH that lacks node, with DIST pointed at a missing path, and with a stale dist. It asserts each run reports failed, not skipped, and that the message names the build hint. The staleness rule is settled here: compare the git commit times of src/host-filters.ts and dist/host-filters.js; fall back to mtime when src has uncommitted changes or either file has no history; a missing git is a failure.</checkpoint>\n<name>Crawler parity and loud failure</name>\n<intent>`test_host_normalisation.py` checks the crawler's compiled `normalizeHostToken` against the same pinned fixture, and the check cannot pass without node and a current `dist/host-filters.js`.</intent>\n<clause_1>`dist/host-filters.js` run under node returns each fixture pair's expected value.</clause_1>\n<clause_2>A missing node, a missing dist or a stale dist makes the crawler test fail rather than skip.</clause_2>\n<files>tests/active/test_host_normalisation.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the two jobs' fetch functions and `sync_hosts`. Both job files are loaded with importlib.util.spec_from_file_location, following the test_similar.py:36-41 precedent, in a module-scoped fixture. Payloads are served from tmp_path as file:// URIs, so no server and no network are needed. Clause 1: a list-shape payload [\"https://Tube.Example/\", \"tube.example\"] gives {\"tube.example\"} from `fetch_hosts`. `ensure_whitelist_schema` plus `sync_hosts` into a tmp_path SQLite file (never the shared whitelist.db) returns (1, 0, 1) and stores exactly the one row \"tube.example\". Clause 2: a dict-shape payload mixing \"\", \"   \", \".\", \"https://\" with valid entries gives {\"tube.example\", \"other.example\"} from both `fetch_hosts` and `fetch_join_hosts`. Regression guard, not a new clause: `fetch_hosts` on a payload where every entry normalises to None still raises ValueError \"Whitelist contained no hosts.\". After the phase, run test-moderation-integration.py, test-orchestrator-smoke.py (report it as not run if node, dist, the embedding stack or network is missing) and validate_tests.py from the worktree, compared with the green baseline.</checkpoint>\n<name>Both jobs normalise through the helper</name>\n<intent>`fetch_hosts` in sync-whitelist.py and `fetch_join_hosts` in updater-worker.py pass every hosts-list entry through `normalize_host_token` in place of `strip().lower()`.</intent>\n<clause_1>`fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`, which `sync_hosts` stores as one row.</clause_1>\n<clause_2>Entries that normalise to None are dropped, and `fetch_join_hosts` returns the same host set as `fetch_hosts`.</clause_2>\n<files>engine/server/db/jobs/sync-whitelist.py (EDITED), engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_host_normalisation.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nPhase 2 needs `node` on PATH in the build environment, plus a committed or rebuilt engine/crawler/dist/host-filters.js (present in the tree now). If node is missing, the checkpoint fails by design, and the operator must install Node.js and run `cd engine/crawler && npm install && npm run build`. The phase 3 post-build run of test-orchestrator-smoke.py also needs the embedding stack and network access; if either is missing, it is reported as not run, not as green. No credentials are needed.\n</needs_coordination>\n\n<rationale>\nThe split follows the three boundaries the drafted implementation already has: the pure Python function, the Node process running the compiled crawler, and the two jobs' fetch/sync functions. Each phase can be verified on its own: phase 1 needs only Python, phase 2 adds node and the dist, and phase 3 adds the job modules and SQLite. Phase 1 lands the helper with the fixture it is judged against, so the fixture exists before anything else depends on it. Phase 2 holds the two facts about the node test (parity, and failing rather than skipping). Those are two clauses on one seam, and this is where the staleness rule (git commit times, with an mtime fallback) gets settled, as the plan asks. Phase 3 holds the requirement that both jobs use the helper, as two observable facts. The existing \"no hosts\" raise is kept as a regression assert rather than a clause, because it is behaviour the tree already has. The doc edits (DATA_BUILD.md, UPDATER_WORKER.md) get no phase and go to Step 9. Three phases, within the limit of 4. The operator approved this breakdown unchanged.\n</rationale>",
    "author:tests/tmp/test_10_normalise_instance_hosts_phase1.py": "<assertions>\ntests/tmp/test_10_normalise_instance_hosts_phase1.py:47 - `tests/active/host_tokens.json`, read when the test runs (line 46, utf-8), has exactly 15 entries, one for each pinned pair. This catches a fixture with a missing, extra or duplicated pair. Wrong version: a fixture that holds only the 14 required pairs, or repeats one, fails. Today the file does not exist, so line 46 raises FileNotFoundError. (C1)\ntests/tmp/test_10_normalise_instance_hosts_phase1.py:48 - the fixture's {input: expected} map equals PINNED, the 15 pairs the test writes out itself at lines 25-41, with JSON null == None. This makes \"each fixture pair\" in C1 the same set of pairs line 53 checks, so an implementer cannot write a fixture to match the port's output and pass. Wrong version: a fixture holding strip/lower or `normalize_host` output (`tube.example` for `tube.example:9000`, `::1` for the IPv6 input, `b\u00fccher.example` for the IDN input, `tube.example` for `https://tube.example./`) gives a different map. (C1)\ntests/tmp/test_10_normalise_instance_hosts_phase1.py:53 - for each of the 15 pinned inputs (parametrised, ids from repr(input)), `moderation.normalize_host_token(value) == expected`, with None where the pinned value is null. The pairs cover every branch. Branch 1: `\"\"` and `\"   \"` \u2192 None. Branch 2: scheme and case; userinfo dropped; port dropped (`http://tube.example:8080/path`); IPv6 re-bracketed (`https://[::1]:8080/` \u2192 `[::1]`); punycode (`https://b\u00fccher.example/` \u2192 `xn--bcher-kva.example`); `https://` \u2192 None; the URL-form dot kept (`https://tube.example./` \u2192 `tube.example.`). Branch 3: `tube.example/videos`. Branch 4: dots trimmed, `.` \u2192 None, port kept (`tube.example:9000`). Wrong versions: a stub returning None fails the 11 non-null cases. Reusing the unchanged `normalize_host` fails the port-keep, `[::1]`, punycode and dotted-URL cases (from reading moderation.py:39-63). Bare `strip().lower()` fails every URL-form case and the dotted bare cases. Today the function does not exist, so each case fails with AttributeError on `data.moderation`, not with a collection error, because the module is imported rather than the name. (C1)\n</assertions>\n\n<probes>\nI ran no probe of my own: this session has no ValidateTests tool, so I could not run anything under tests/tmp. The only thing I observed is the workflow's collect-only run of the previous version. It exited 2 with `ImportError: cannot import name 'normalize_host_token' from 'data.moderation' (/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts/engine/server/data/moderation.py)`. That shows `ROOT = Path(__file__).resolve().parents[2]` plus the `SERVER_DIR` insert resolve `data.moderation` to the worktree's engine/server module, and that the missing name, not a path, is what failed. Fix: the file now imports the module (`import data.moderation as moderation`, line 20), reads the fixture inside the test (line 46), and parametrises over the literal PINNED, so nothing at import time needs this phase's code. Expected collect count, not observed: 16 (1 fixture test plus 15 cases). Expected red on the current tree, also not observed: FileNotFoundError at line 46, and AttributeError at line 53 in all 15 cases. Both are this phase's missing deliverables. The 15 expected values are not observed either. 14 are the WHATWG values the requirements pin, and the 15th (`https://tube.example./` \u2192 `tube.example.`) comes from the plan. They can be confirmed by running the crawler's `dist/host-filters.js` `normalizeHostToken` over the same inputs, which is phase 2's C1, or by this checkpoint going green after implementation.\n</probes>\n\n<unassertable>\nnone. C1 is fully carried. The test differs from the Step 6 seam wording in two ways, both needed to collect and to avoid passing by construction. (1) The parametrised test runs over the literal PINNED, not over the fixture's pairs. `tests/active/host_tokens.json` does not exist until this phase writes it, and parametrisation runs at collection, so parametrising over the fixture fails collection (the exit 2 above), as would the draft's module-level `json.loads`. The fixture is still read at run time, and line 48 asserts that its pairs equal PINNED, so every fixture pair is checked at line 53, with the ids still from repr(input). This also stops the implementer from writing a fixture that matches the port. My previous reply said the parametrised test \"still iterates over the fixture\"; that was inaccurate and is corrected here. (2) `ROOT` is computed as `Path(__file__).resolve().parents[2]`, as test_db.py does, and not imported from conftest. `tests/tmp/` has no conftest, and the collect-only output shows this resolves `engine/server` correctly.\n</unassertable>",
    "self_check:tests/tmp/test_10_normalise_instance_hosts_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase1.py:53 \u2014 for each of the 15 pinned inputs (parametrised, ids repr(input)), `moderation.normalize_host_token(value) == expected`, with None where the pinned value is null</assertion>\n<expected>The pinned value for each input. \"tube.example\" for the 7 trim, dot, scheme, userinfo, port and path inputs. \"tube.example:9000\", \"[::1]\" and \"xn--bcher-kva.example\". \"tube.example.\" for \"https://tube.example./\". None for \"\", \"   \", \".\" and \"https://\". The first 14 are the WHATWG values pinned in the operator-confirmed requirements. The 15th comes from the approved plan's fixture. No run has shown me any of them; see answers 7 and 10.</expected>\n<wrong_implementation>A stub returning None fails the 11 non-null cases. Reusing the unchanged `normalize_host` fails \"tube.example:9000\" (port dropped, giving \"tube.example\"), \"https://[::1]:8080/\" (gives \"::1\" with no brackets), \"https://b\u00fccher.example/\" (no punycode) and \"https://tube.example./\" (dot stripped, giving \"tube.example\"); I got this from reading moderation.py:39-63, not from a run. Bare `strip().lower()` fails every URL-form case and every dotted case. Stripping the dot in branches 2 and 3 fails the \"https://tube.example./\" case.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase1.py:47-48 \u2014 `tests/active/host_tokens.json`, read at run time, has exactly 15 entries, and its {input: expected} map equals PINNED (JSON null == None)</assertion>\n<expected>15 entries, and a map equal to PINNED. This makes \"each fixture pair\" in C1 exactly the pairs that line 53 checks.</expected>\n<wrong_implementation>A fixture written to match the port's output would let line 53 and a fixture-driven test pass by construction. Such a fixture gives a different map here: \"tube.example\" for \"tube.example:9000\", \"::1\" for the IPv6 input, \"b\u00fccher.example\" for the IDN input. A fixture holding only the 14 required pairs, or one with a duplicated or extra pair, gives a different count or map.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, both are covered. The docstring makes two claims. First, the fixture holds exactly the 15 pinned pairs; lines 47-48 check this. Second, `normalize_host_token` returns the pinned value, or None, for each of those pairs; line 53 checks this. Together they carry C1's \"each fixture pair's expected value, and None where null\". Nothing rewritten this round.\n2. Absence only: no. There is no negative assertion. The four None cases are equality checks in the same table as the 11 non-null cases, and those act as their control.\n3. Echoed literal: no. The test does no normalisation of its own. Expected values come from the PINNED literal at lines 25-41, never from the function under test. Deleting the new `normalize_host_token` body in engine/server/data/moderation.py turns line 53 red. Deleting or changing tests/active/host_tokens.json turns line 46/47/48 red.\n4. One value: no. The observable is read at 15 inputs across all four branches. Each result is compared with an independent literal, not with a sibling output from the same source.\n5. The double: no. There are no doubles; the real `data.moderation` module is imported at line 20.\n6. It collects: yes, and this time I have seen it. tests/last_test_output.txt, written by the workflow's `--collect-only -q` run (exit 0), lists `test_fixture_holds_exactly_the_pinned_pairs` plus 15 `test_normalize_host_token_returns_pinned_value[...]` ids and ends \"16 tests collected in 0.01s\". That matches the 1 + 15 I wrote. The import resolves: `ROOT = parents[2]` plus the SERVER_DIR insert finds the worktree's engine/server/data/moderation.py. The runner's lane summary line says \"no tests\" only because collect-only runs nothing; the collected list itself shows 16.\n7. Observed, not predicted: no expected value comes from a run of mine, and I could not change that this turn. This session has no ValidateTests tool; it has only Read, Write, Edit, Glob, Grep, AstGrep, AskUser and Submit. So I could not run a probe under tests/tmp or run node on engine/crawler/dist/host-filters.js. Where the values come from: 14 are the WHATWG values pinned in the operator-confirmed requirements (\"Expected values are the WHATWG results; the Node check confirms them against the crawler's real output\"). The 15th (\"https://tube.example./\" \u2192 \"tube.example.\") is from the approved plan's 15-pair fixture (plan lines 696-718). All 15 are the judged expectations of the phase; no control assertion depends on them, so none can fail on its own setup. Two runs would confirm or refute them: phase 2's C1, which runs node on the crawler's normalizeHostToken over the same fixture inputs, or this checkpoint going green once the phase is built. I did not rewrite anything for this. Dropping or changing a pinned value without a run would replace one prediction with another, and would move the test away from the approved requirements and plan.\n8. Red, not green: not observed. I could not run ValidateTests; the tool is not available in this session. The only run recorded for this file is the workflow's collect-only: tests/last_test_validation.json shows target [\"tests/tmp/test_10_normalise_instance_hosts_phase1.py\", \"--collect-only\", \"-q\"], \"exit_code\": 0, \"16 tests collected in 0.01s\". That run executed no test. From reading the tree, not from a run, I expect all 16 to fail on the current code, for two reasons. `def normalize_host_token` appears nowhere in engine/server/data/moderation.py (its defs are normalize_host, ensure_moderation_schema, ... _row_value). And tests/active/host_tokens.json does not exist: Glob of tests/** lists no json under tests/active. The build's own run after this turn will be the first real observation.\n9. Red for the right reason: not observed, for the same reason. Expected, not seen: line 46 raises FileNotFoundError for tests/active/host_tokens.json in test_fixture_holds_exactly_the_pinned_pairs. Line 53 raises AttributeError (\"module 'data.moderation' has no attribute 'normalize_host_token'\") in each of the 15 parametrised cases. Both are this phase's own missing deliverables, the fixture and the function. They are not a typo, a wrong path (the collect-only run shows data.moderation resolves) or a harness limit. No control assertion comes before the judged ones, so a control cannot fail first. This is a prediction until the build's run confirms it.\n10. Observed expected output: not observed. Both rows state the pinned requirement values and say plainly that no run has shown them. No run of mine contradicts any value, because I have none. The build's post-turn run can confirm the red. The values themselves will be confirmed or contradicted by phase 2's node parity check and by this checkpoint after implementation.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\nNothing needed writing this turn. All three files in this phase were already in the worktree when the turn started. I checked each against the crawler source and the checkpoint's pinned values, and left them unchanged. I did not write them in this turn, so they came from an earlier pass over this step.\n\n### `engine/server/data/moderation.py`\n- `normalize_host_token(value: str) -> str | None` sits directly after `normalize_host`, which is unchanged. It is a line-for-line port of `normalizeHostToken` in `engine/crawler/src/host-filters.ts`:\n  - strips and lowercases the input, and returns None if nothing is left;\n  - sends `http://` / `https://` inputs through `_whatwg_hostname`;\n  - sends inputs containing `/` through `_whatwg_hostname` as `https://{raw}`;\n  - otherwise strips leading and trailing dots, returning None if nothing is left;\n  - catches a single `ValueError`, which stands in for the crawler's try/catch around the whole body.\n- `_whatwg_hostname(url)` is a private helper that returns the hostname WHATWG `URL.hostname` would give:\n  - reads `urlparse(...).port` so a bad port raises, as WHATWG does;\n  - returns None for an empty host;\n  - puts brackets around the compressed form of IPv6 literals;\n  - IDNA-encodes only non-ASCII hosts.\n  - It carries a `rat-tail:` comment: `urlparse` accepts forbidden host code points that WHATWG rejects, so the two only match on the pinned inputs. The fix is a forbidden-code-point check in this helper once a fixture input exposes the gap.\n- The module header comment names both normalisers and what each is for.\n- New imports: `ipaddress` and `urlparse`. New module constant: `URL_SCHEME_PREFIXES`.\n\n### `tests/active/host_tokens.json`\n- Contains exactly the 15 `{\"input\", \"expected\"}` pairs from the requirements, with `null` meaning None. I compared them one by one against the checkpoint's `PINNED` dict and they match.\n\n### `tests/active/test_host_normalisation.py`\n- A durable test, parametrised over every pair in `host_tokens.json`, that asserts `normalize_host_token(input) == expected`. It gets `ROOT` from `tests/active/conftest.py`, which I confirmed exports it.\n\n### What I ran\n- I wrote a probe, `tests/tmp/probe_host_token.py`, that runs all 15 fixture pairs through `normalize_host_token` and asserts none of them mismatch. It passed (exit 0). I did not run the gating checkpoint myself.\n- I have no delete tool, so the probe is still in the tree. The operator can remove it with `rm tests/tmp/probe_host_token.py`; it gates nothing.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_10_normalise_instance_hosts_phase2.py": "<items>\n<item id=\"C1b\">\n<disposition>fixed</disposition>\n<what>New `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input`, parametrized over all 15 inputs in `tests/active/host_tokens.json`. For each input it renames dist's `normalizeHostToken` to `pinnedNormalizeHostToken` and appends a wrapper export that returns `wrong-host.invalid` for that one input and passes every other input through. A control at :180 checks under node that this dist differs from PINNED on that input and nowhere else. The dist is committed after src, so it is current. Then :184 (`outcome == \"failure\"`) and :185 (`WRONG_HOST in message`) require the durable test to fail on the wrong value, and :186 requires that failure not to be reported as staleness. A durable test that leaves out any one fixture pair passes the run for that pair and turns it red. Observed in the harness: a `subset` variant that drops the last pair failed only at `['https://tube.example./']`, and the correct variant passed all 15.</what>\n</item>\n<item id=\"D2\">\n<disposition>fixed</disposition>\n<what>The premise test now asserts that the fixture is PINNED. :162 checks `len(FIXTURE_PAIRS) == len(PINNED)`, so a duplicated input cannot hide inside a dict, and :163 checks `{pair[\"input\"]: pair[\"expected\"] for pair in FIXTURE_PAIRS} == PINNED`. The docstring now says this outright (\"`tests/active/host_tokens.json` holds exactly those 15 pairs\"). If the fixture drifts from the hand-written requirement values, the test goes red, and the chain \"Python port equals fixture equals PINNED equals dist\" is now checked at every link.</what>\n</item>\n<item id=\"D4\">\n<disposition>fixed</disposition>\n<what>I removed the unasserted description of the real tree's state from the docstring, which now says only \"passes on this tree\" (:169 carries that). The :167 comment now records that state as something seen when the test was written, not something asserted. The boundary the phrase described is now asserted in a repo the test controls: `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk` commits dist and src at the same time, leaves src clean, makes dist an hour older on disk, and :242 asserts `outcome == \"passed\"`. The docstring's last bullet now includes \"or at the same time as a clean src, though older on disk\".</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (whole-claim, C1 one mutation hits one pair): added the 15-way parametrized per-fixture-input test at :172\u2013186. Each run makes the current dist wrong on exactly one input (control at :180) and requires failure (:184) with the wrong value in the message (:185). A durable test checking only some pairs now goes red on each pair it leaves out. Observed with a `subset` probe variant.\nClaim RECOMMENDATION 1 (D2), taken: :162\u2013163 assert that the fixture holds exactly the PINNED pairs.\nClaim RECOMMENDATION 2 (D4), taken: the docstring no longer asserts the real tree's state, and :167 records it as seen when the test was written. The boundary is pinned in a controlled repo instead (:242).\nClaim RECOMMENDATION 3 (bounds), taken: new `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk`, with equal commit times, clean src and dist older on disk, expects passed (:242). Observed: the `mtime_only` and new `equal_is_stale` (>= commit rule) probe variants both go red there.\nShape RECOMMENDATION 1 (`\"git\" in message` at :270): left as is. The durable test's git-missing wording is not pinned by any requirement, so any exact string I chose would be invented.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>test_10_normalise_instance_hosts_phase2.py:160 \u2014 node running the real dist returns exactly PINNED for all 15 inputs. :163 \u2014 the fixture's pairs are exactly PINNED. :169 \u2014 the durable crawler test reports passed on this tree. :184/:185 \u2014 for each of the 15 fixture inputs in turn, with a current dist wrong on that input alone (control :180), the durable test reports failure and the message contains `wrong-host.invalid`. :197/:198 \u2014 with the realistic `.toLowerCase()` removal, it fails naming 'Tube.Example'.</assertion>\n<expected>:160 and :163 equality holds. :169 \"passed\". :184 \"failure\" and :185 true for every one of the 15 parametrized inputs. :197 \"failure\" with 'Tube.Example' in the message.</expected>\n<wrong_implementation>A durable crawler test that compares only some fixture pairs (observed with the `subset` variant, which drops the last pair): :184 reads \"passed\" for `'https://tube.example./'`. One that never compares dist's output (`no_compare`): :184 reads \"passed\" for all 15. One that skips or does not exist: :169 reads \"skipped\"/\"not collected\". A fixture that has drifted from the requirements: :163 goes red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_10_normalise_instance_hosts_phase2.py:205/:206 (no node), :211/:212 (missing dist), :222/:223 (src committed after dist, dist newer on disk), :253/:254 (uncommitted src edit, equal commit times), :262/:263 (dist has no history and is older): each asserts outcome == \"failure\" and the build hint in the junit message. :269 fails without git. Contrasts: :232 and :242 assert \"passed\" when dist was committed after src, or at the same time as a clean src, though older on disk. :186 and :199 assert that a current-but-wrong dist is not reported as stale.</assertion>\n<expected>\"failure\" with BUILD_HINT in the message in each stale, missing or no-node scenario. \"passed\" at :232 and :242. No BUILD_HINT at :186 and :199.</expected>\n<wrong_implementation>pytest.skip on a missing node: :205 reads \"skipped\". Mtime-only staleness: :222 reads \"passed\", and :232 and :242 read \"failure\". Commit-time-only staleness: :253 and :262 read \"passed\". A >= commit-time rule: :242 reads \"failure\". A test that always fails with the hint: :169 and :232 read \"failure\".</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Each BUILD_HINT-absent check (:186, :199) is paired with outcome == \"failure\" and the wrong value present in the message. If the durable test is deleted, every run reads \"not collected\" and goes red.\n2. No. PINNED is hand-written from the requirements. The per-input expectation at :180 is PINNED with one key replaced by a sentinel the test itself injects, not a recomputation of normalizeHostToken. Removing `.toLowerCase()` from dist's normalizeHostToken, or dropping any pair from the durable test's comparison, turns a run red.\n3. No. That was the CRITICAL, and it is fixed: the wrong-value observable is now read at all 15 fixture inputs (:172) as well as the realistic mutation (:189). The freshness outcome is read at seven controlled states plus this tree.\n4. No. No double. The only rewrite is a real copy of the crawler's own dist with one export wrapped, run under real node. The SRC/DIST redirect plugin only repoints paths.\n5. Yes, it collects. `import pytest` was added. FIXTURE_PAIRS, EXPORT_LINE, WRONG_HOST and `_dist_outputs` are all bound. The harness collected 27 checkpoint tests (10 + 15 parametrized + 1 new, plus the premise test) across 8 variants, 208 in total, and all ran.\n6. Yes. ValidateTests [\"tests/tmp/probe_phase2_harness.py\", \"-q\", \"-rfE\"] ran the edited checkpoint against the probe durable copy: 180 passed, 28 failed. The correct variant passed everything, which confirms the :180 control holds under node and that `wrong-host.invalid` appears in the junit message. `subset` failed only at the dropped pair, and `equal_is_stale` failed at :169 and :242.\n7. Predicted, not observed. I did not run the gating checkpoint against today's phase-1 durable file, because that run belongs to the workflow. There, `-k crawler_dist` selects nothing, so every durable-run assertion reads \"not collected\" and goes red, while the premise test (:160, :163) passes, since the fixture and PINNED match on disk. Probe files I cannot delete and that need the operator to remove them (none matches test_*.py): tests/tmp/probe_phase2_env.py, tests/tmp/probe_durable_host.py, tests/tmp/probe_phase2_harness.py.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_10_normalise_instance_hosts_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:154 \u2014 `pytest tests/active/test_host_normalisation.py -k crawler_dist` runs in its own process on this tree and its junit outcome is \"passed\"</assertion>\n<expected>\"passed\". The harness run's correct variant showed this: probe_phase2_harness.py `test_durable_crawler_test_passes_on_this_tree[correct]` PASSED. Today the outcome is \"not collected\": the run printed `assert 'not collected' == 'passed'` at line 154.</expected>\n<wrong_implementation>An mtime-only staleness rule. This tree's dist is committed with src but is a few ms older on disk, so that rule fails the durable test. Observed in the harness: `[mtime_only]` FAILED with `AssertionError: Failed: older; run: cd engine/crawler && npm install && npm run build / assert 'failure' == 'passed'`. With no durable test at all (today's tree), it reads \"not collected\".</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:165-166 \u2014 setup: a dist that is current by git (committed after src) but has `.toLowerCase()` removed, so only \" Tube.Example \" comes out wrong. Asserted: the durable test's outcome is \"failure\", and junit's message attribute contains 'Tube.Example'</assertion>\n<expected>\"failure\", with 'Tube.Example' in the junit message. Observed: the harness's `test_durable_crawler_test_fails_on_current_dist_with_one_wrong_value[correct]` PASSED, now reading only the message attribute. Today: `assert 'not collected' == 'failure'` at line 165.</expected>\n<wrong_implementation>A durable test that runs node and checks only its returncode, never comparing the output to the fixture. It reports \"passed\" here. Observed: harness `[no_compare]` FAILED with `assert 'passed' == 'failure'` at line 165.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:173-174 \u2014 with a PATH holding only git (no node), the durable test's outcome is \"failure\", and junit's message contains \"cd engine/crawler && npm install && npm run build\"</assertion>\n<expected>\"failure\", with the build hint in the message. Observed: harness `test_durable_crawler_test_fails_loudly_without_node[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 173.</expected>\n<wrong_implementation>`pytest.skip` when node is missing. Observed: harness `[skip]` FAILED with `AssertionError: no node / assert 'skipped' == 'failure'` at line 173.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:179-180 \u2014 with DIST redirected to a missing path, the outcome is \"failure\" and junit's message (not the traceback text) contains the build hint</assertion>\n<expected>\"failure\", with the build hint in the message. Observed: harness `test_durable_crawler_test_fails_loudly_when_dist_is_missing[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 179.</expected>\n<wrong_implementation>No dist-existence check, with the hint text written literally in the test's source. The durable test then fails on git or node, not with the hint. Observed: harness `[no_dist_check]` FAILED at line 180 with `assert 'cd engine/crawler && npm install && npm run build' in \"subprocess.CalledProcessError: Command '['/usr/bin/git', 'log', ...]' returned non-zero exit status 128.\"`. Before this rewrite the same variant PASSED (`-k \"no_dist_check and dist_is_missing\"`: 1 passed), because the traceback text listed the literal.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:190-191 \u2014 setup: src committed after dist (2021 vs 2020), but dist newer on disk. Asserted: outcome \"failure\" with the build hint in the message</assertion>\n<expected>\"failure\", with the hint. Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 190.</expected>\n<wrong_implementation>An mtime-only rule sees dist as newer and passes. Observed: harness `[mtime_only]` FAILED with `assert 'passed' == 'failure'` at line 190.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:200 \u2014 with dist committed after src but older on disk, the outcome is \"passed\". This is the positive side of the staleness rule: commit time wins for committed files</assertion>\n<expected>\"passed\". Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'passed'` at line 200.</expected>\n<wrong_implementation>An mtime-only rule, or one that is always stale. Observed: harness `[mtime_only]` FAILED with `Failed: older; run: ... / assert 'failure' == 'passed'` at line 200.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:211-212 \u2014 setup: equal commit times, an uncommitted src edit, and dist older on disk. Asserted: outcome \"failure\" with the build hint in the message</assertion>\n<expected>\"failure\", with the hint. Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 211.</expected>\n<wrong_implementation>A git-only rule that ignores a dirty src. Observed: harness `[git_only]` FAILED with `assert 'passed' == 'failure'` at line 211.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:220-221 \u2014 with dist never committed (no history) and older on disk than src, the outcome is \"failure\" with the build hint</assertion>\n<expected>\"failure\", with the hint. Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 220.</expected>\n<wrong_implementation>A git-only rule that treats missing history as current. Observed: harness `[git_only]` FAILED with `assert 'passed' == 'failure'` at line 220.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase2.py:227-228 \u2014 with a PATH holding only node (no git) on this tree, the outcome is \"failure\" and junit's message names git</assertion>\n<expected>\"failure\", with a message such as \"Failed: git is not on PATH, so the freshness of dist/host-filters.js cannot be checked; run: ...\". Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 227.</expected>\n<wrong_implementation>An mtime-only rule never needs git and fails for the wrong reason, the checkout's mtime order. Observed: harness `[mtime_only]` FAILED at line 228 with `assert 'git' in 'Failed: older; run: cd engine/crawler && npm install && npm run build'`. A rule that treats a missing git as current would report \"passed\" at line 227.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes. Every docstring bullet has an assertion. C1 is carried by the durable test passing on this tree (line 154) and failing on a current dist with one wrong value (165-166). The direct node run (142-148) was relabelled as a premise control: it is true before the phase and carries no clause. C2 is carried by the missing-node, missing-dist and three stale scenarios, each with outcome == \"failure\" plus the hint in the message. It is bounded by two positive scenarios: committed-after-src passes (200) and no git fails (227-228). The one-wrong-value test also checks that a current dist does not get the hint (167).\n2. Absence only: one negative assertion, `BUILD_HINT not in message` at line 167. The same test's `outcome == \"failure\"` (165) and `'Tube.Example' in message` (166) arm it, since they prove the durable test ran and failed on the value comparison. Before the rewrite, the hint checks had a related hole: they searched the junit traceback text, which lists the durable test's source. The harness's new `no_dist_check` variant (no dist check, hint written literally in the source) PASSED the missing-dist test against the old checkpoint: `-k \"no_dist_check and dist_is_missing\"` gave 1 passed, exit 0. Rewritten: `_run_crawler_test` now returns only junit's `message` attribute, and the same variant now FAILS at line 180.\n3. Echoed literal: no. PINNED is written out independently of the fixture and the crawler. The checkpoint never normalises anything itself. Deleting the durable test's `pytest.fail(... BUILD_HINT)` for missing node, or its dist-existence check, or its fixture comparison, turns 173, 179/180 or 165 red respectively. The harness variants skip, no_dist_check and no_compare showed exactly that.\n4. One value: no. The staleness rule is read at six distinct git/mtime configurations, three outcomes each way, and the node gate at two PATHs. The wrong-value case compares against the independent fixture, not a sibling run.\n5. The double: none of the project's modules is replaced. The only redirection is the plugin that rebinds the durable test's SRC/DIST Path constants to a scenario's copies, plus GIT_DIR/GIT_WORK_TREE. The durable test, node, git and the real dist all run for real. The plugin raises if a constant is missing, so a rename errors instead of passing.\n6. It collects: yes. The runs printed \"collected 10 items\", which matches the 10 test functions. The workflow's collect-only line said \"no tests\" only because that lane summary counts outcomes and collect-only produces none.\n7. Observed, not predicted: yes. Every expected outcome and message fragment comes from the harness run (tests/tmp/probe_phase2_harness.py, run with -rA: 9 failed, 51 passed, exit 1). It runs the checkpoint against a copy of the planned durable test in six variants. The correct variant passed all 10 tests. Each wrong variant failed exactly where its row says, and the failure messages are quoted in the rows. The PINNED values come from an earlier probe run of node on the real dist. That the junit message attribute alone carries \"Failed: <text>\" and 'Tube.Example' was observed in this same run.\n8. Red, not green: yes. The final run of tests/tmp/test_10_normalise_instance_hosts_phase2.py had exit status 1: \"9 failed, 1 passed\". The one green, test_crawler_dist_under_node_returns_pinned_values, is a premise control that is true before the phase, and no row names it. The phase's own claims (lines 154-228) are all red.\n9. Red for the right reason: now yes. In the first run this turn, all 9 failures were the line-86 control `assert len(cases) == 1 and \"crawler_dist\" in ...` failing on `assert (0 == 1)`, with the nested pytest saying \"collected 15 items / 15 deselected / 0 selected\". That is a failed control, so I rewrote it. The control is now `len(cases) <= 1`, which passes today. An empty selection is returned as the outcome \"not collected\", which every judged assertion rejects. After the rewrite each failure is a judged assertion: line 154 `assert 'not collected' == 'passed'`; lines 165, 173, 179, 190, 211, 220 and 227 `assert 'not collected' == 'failure'`; line 200 `assert 'not collected' == 'passed'`. The cause is that tests/active/test_host_normalisation.py has no crawler_dist test yet, which is this phase's deliverable.\n10. Observed expected output: every row's expected value is what the harness's correct variant produced, and every wrong-implementation reading is quoted from the failing variant's output. The one place a run contradicted me was the old checkpoint passing the no_dist_check variant. That drove the message-attribute rewrite, and the rerun confirms line 180 now goes red for that variant. Housekeeping: I have no delete tool, so the probes remain for the operator to remove: tests/tmp/probe_phase2_env.py, tests/tmp/probe_durable_host.py (now with a no_dist_check variant) and tests/tmp/probe_phase2_harness.py. None matches test_*.py.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `tests/active/test_host_normalisation.py`\n- I added one test, `test_crawler_dist_returns_pinned_values`. It is not parametrized, so `-k crawler_dist` selects exactly that one test. It runs through these checks in order:\n  1. `node` must be on PATH. If not, it fails with the build hint `cd engine/crawler && npm install && npm run build`.\n  2. `DIST` must exist. If not, it fails with the build hint.\n  3. `git` must be on PATH. If not, it fails and names git.\n  4. `DIST` must not be older than `SRC`. If it is, it fails with the build hint.\n  5. It loads `DIST` in node through its file:// URL, runs `normalizeHostToken` on every input in `host_tokens.json`, and fails if any value differs. The message lists each wrong input with `repr(actual)` and `repr(expected)`, and has no build hint.\n- `_dist_is_stale` decides step 4:\n  - When both files are committed and clean, it compares git commit times (`git log -1 --format=%ct`) with a strict `>`. A checkout sets file mtimes arbitrarily, so on a clean tree they mean nothing.\n  - When either file shows in `git status --porcelain` (an edit, or never committed) or has no commit, it compares mtimes instead.\n  - git runs from `ROOT`, so `GIT_DIR`/`GIT_WORK_TREE` in the environment can point it at another repo.\n- The paths are the module-level `Path` constants `SRC` and `DIST`, read when the test runs, not at import. `BUILD_HINT` and `NODE_SCRIPT` are also module level.\n- The module docstring has a new bullet for the crawler test. Added imports: `os`, `shutil`, `subprocess`.\n- Nothing calls `pytest.skip`, so a missing prerequisite always fails the test.\n\n### Probe (checked, then emptied)\nI ran a throwaway probe, `tests/tmp/probe_git_outside_worktree.py`, and saw:\n- With `GIT_DIR`/`GIT_WORK_TREE` set and git run from outside that work tree, absolute pathspecs work. `status` shows `??` for an untracked file and ` M` for an edited one, and `log` gives no output for a file never committed.\n- In the real tree, src and dist are clean and both have commit time 1790369883.\n- The new durable test passes on this tree when run in its own pytest with junit output.\n- A long custom assert message comes through complete in junit's `message` attribute.\n- Python is 3.14, so `zip(strict=True)` is available.\n\nI haven't run the checkpoint itself, so none of its other scenarios have been seen passing yet: wrong values, missing node/git/dist, and the stale and not-stale git cases. The workflow's run of the checkpoint will be the first check of those. I had no delete tool, so the probe file is emptied to a docstring and still needs deleting.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_git_outside_worktree.py \u2014 the probe I used to check git behaviour and the junit message before writing the test. It now holds only a docstring (no tests) because I had no delete tool; please delete it.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_10_normalise_instance_hosts_phase3.py": "<items>\n<item id=\"D1\">\n<disposition>justified</disposition>\n<what>I narrowed the docstring's summary sentence on line 1 so it matches what the test asserts. It no longer says the jobs normalise \"with `normalize_host_token`\". It now says they \"normalise hosts-list entries to bare lowercase hosts, as pinned by the literal inputs below\". No assertion claims to tie either fetcher to that function. The claim that matters, that both fetchers agree on the same host set (C2b), is still carried at :58 and :59. I did not add an assertion that runs `normalize_host_token` inside the test. That would make the test perform production's own transformation and compare production with itself, which is the mirroring the shape audit warns about. Only the docstring line changed, so every assertion keeps its line number.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. I did not take any of the three claim-audit RECOMMENDATIONS. Rec 1 (D1) I handled by narrowing the docstring, not by adding an assertion that mirrors normalize_host_token. Rec 2 (fetch_join_hosts on an all-None payload) and rec 3 (null or non-string entries, and the list payload through fetch_join_hosts) would pin behaviour that no must_prove clause asks for. I left them as they are. They do not block.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:44, :48, :49 \u2014 fetch_hosts([\"https://Tube.Example/\", \"tube.example\"]) == {\"tube.example\"}; then sync_hosts on a fresh tmp_path schema == (1, 0, 1); then the instances table holds exactly [(\"tube.example\",)]</assertion>\n<expected>{\"tube.example\"}, then (1, 0, 1), then [(\"tube.example\",)]</expected>\n<wrong_implementation>Strip-and-lowercase only, which is the pre-phase code. On a run it returned {\"https://tube.example/\", \"tube.example\"}, and syncing that set gives (2, 0, 2) and two rows (the probe observed SYNC_OLD (2, 0, 2)).</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:58, :59 \u2014 fetch_hosts and fetch_join_hosts, fed the same {\"data\": [...]} payload (\"\", \"   \", \".\", \"https://\", \"tube.example.\", \"https://Other.Example/videos\"), each return exactly {\"tube.example\", \"other.example\"}</assertion>\n<expected>{\"tube.example\", \"other.example\"} from both fetchers</expected>\n<wrong_implementation>Pre-phase strip/lower in either job. On a run it returned {\".\", \"https://\", \"tube.example.\", \"https://other.example/videos\"}. Also excluded: updater-worker left on its own normaliser while sync-whitelist is fixed, which fails :59 on its own.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. There is no absence-only assertion. Every check is an exact set, tuple or row list with positive members, and the raise at :65 is a positive pytest.raises check with an anchored message.\n2. No. Every expected value is a literal, and the test does not normalise anything itself. That is why I narrowed the docstring and did not add a normalize_host_token comparison. Deleting the new normalisation call in fetch_hosts turns :44, :58 and :65 red. Deleting it in fetch_join_hosts turns :59 red.\n3. No. Normalisation is checked on six distinct inputs across two payload shapes, and C2b holds two independent fetchers to one literal set, not to each other.\n4. No. There are no doubles. The real modules are loaded, the fetchers read a real file:// URI, and sync_hosts writes to a real SQLite file.\n5. Yes, it collects. Only the docstring changed. The imports, names and three test functions are unchanged from the version that collected and ran in the earlier probe.\n6. Yes, the values were observed. The pre-phase outputs and SYNC_ONE (1, 0, 1) [('tube.example',)] come from the earlier ValidateTests runs quoted in my previous reply.\n7. Yes, it is still red for its own reason. The docstring edit touches no executable line, so the earlier run still stands: all three tests fail on their assertions because the phase has not been built.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_10_normalise_instance_hosts_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:44 \u2014 `sync_whitelist.fetch_hosts(url)` on the list payload `[\"https://Tube.Example/\", \"tube.example\"]`, served as a tmp_path file:// URI, `== {\"tube.example\"}`</assertion>\n<expected>{\"tube.example\"}. The probe ran `normalize_host_token` on both entries and got 'tube.example' for each, so a job that routes entries through it yields this one-element set.</expected>\n<wrong_implementation>The current `str(host).strip().lower()` at sync-whitelist.py:243. The checkpoint run showed it returns {'https://tube.example/', 'tube.example'} (\"Extra items in the left set: 'https://tube.example/'\"). Calling `normalize_host` instead of `normalize_host_token`, or lowercasing without stripping the scheme, also keeps the two spellings apart.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:48 \u2014 `sync_whitelist.sync_hosts(conn, hosts) == (1, 0, 1)` on a fresh `ensure_whitelist_schema` in a tmp_path SQLite file, with `hosts` taken from the fetch at line 43</assertion>\n<expected>(1, 0, 1). The probe got SYNC_ONE (1, 0, 1) for {\"tube.example\"} on a fresh schema.</expected>\n<wrong_implementation>With the un-normalised fetch, `hosts` holds both spellings. The probe got SYNC_TWO (2, 0, 2) for {\"tube.example\", \"https://tube.example/\"}, which this assertion rejects even if line 44 were loosened.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:49 \u2014 `SELECT host FROM instances` on the same connection returns exactly `[(\"tube.example\",)]`</assertion>\n<expected>[('tube.example',)]. The probe got ROWS_ONE [('tube.example',)] after syncing {\"tube.example\"}.</expected>\n<wrong_implementation>Storing both spellings, as the un-normalised fetch does. The probe got ROWS_TWO [('https://tube.example/',), ('tube.example',)].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:58 \u2014 `sync_whitelist.fetch_hosts(url)` on the `{\"data\": [{\"host\": e}, ...]}` payload of \"\", \"   \", \".\", \"https://\", \"tube.example.\", \"https://Other.Example/videos\" `== {\"tube.example\", \"other.example\"}`</assertion>\n<expected>{\"tube.example\", \"other.example\"}. The probe got None for \"\", \"   \", \".\" and \"https://\", 'tube.example' for \"tube.example.\" and 'other.example' for \"https://Other.Example/videos\" from `normalize_host_token`.</expected>\n<wrong_implementation>The current strip/lower. Both the checkpoint run and the probe (SYNC_NOW) returned {'.', 'https://other.example/videos', 'tube.example.', 'https://'}, so \".\" and \"https://\" are kept instead of dropped. An implementation that normalises but then adds a None or empty value to the set would also differ. The two kept hosts serve as the positive control: an implementation that drops everything fails too.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:59 \u2014 `updater_worker.fetch_join_hosts(url)` on the same payload `== {\"tube.example\", \"other.example\"}`, the same literal as line 58, so the two fetchers must agree with each other</assertion>\n<expected>{\"tube.example\", \"other.example\"}, by the same observed `normalize_host_token` values as line 58.</expected>\n<wrong_implementation>Changing only sync-whitelist.py and leaving updater-worker.py:438 as `str(host).strip().lower()`. The probe (JOIN_NOW) showed that returns {'.', 'https://other.example/videos', 'tube.example.', 'https://'}, so line 58 would pass and this line would fail.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:65 \u2014 `fetch_hosts` on the list payload \"\", \"   \", \".\", \"https://\" raises ValueError whose message is exactly \"Whitelist contained no hosts.\"</assertion>\n<expected>ValueError(\"Whitelist contained no hosts.\"). The probe showed all four entries normalise to None, which leaves the set empty and reaches the existing raise at sync-whitelist.py:248.</expected>\n<wrong_implementation>The current strip/lower. The checkpoint run showed \"Failed: DID NOT RAISE ValueError\", because \".\" and \"https://\" survive into the set. An implementation that adds the None results to the set would also avoid the raise.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, every claim is tested. Docstring bullet 1 (fetch collapses the two spellings, and `sync_hosts` returns (1, 0, 1) and leaves the one row) is lines 44, 48 and 49. Bullet 2 (both fetchers drop the entries that normalise to None and return exactly {tube.example, other.example}) is lines 58 and 59. Bullet 3 (the empty-set raise is kept) is line 65. For C2's \"fetch_join_hosts returns the same set as fetch_hosts\", both fetchers are compared to one literal, which implies they are equal. Nothing rewritten.\n2. Absence only: no. The dropping is asserted by set equality, and the same set requires \"tube.example\" and \"other.example\" to be present, so a fetcher that drops everything fails. Line 65 is a positive check that the exception is raised, with the message anchored.\n3. Echoed literal: no. The test normalises nothing itself; every expected value is a literal. Reverting sync-whitelist.py:243 to `host_value = str(host).strip().lower()` turns lines 44, 58 and 65 red; the current run shows exactly that. Reverting updater-worker.py:438 (`value = str(host).strip().lower()`) turns line 59 red; the probe's JOIN_NOW showed the wrong set.\n4. One value: no. Collapsing is read on a list payload (URL spelling plus bare spelling). Dropping is read on a dict payload with four None-normalising entries plus two different surviving forms (trailing dot, URL with a path). The empty case is a third payload. Line 59 compares against an independent literal, not against line 58's output.\n5. The double: no. There are no doubles. The real job modules are loaded from engine/server/db/jobs, and `data.moderation` and `urlopen` are real. Payloads go through a real file:// URI, which the run showed `urlopen` accepts with the Request headers.\n6. It collects: yes. The workflow's collect-only run (exit 0) wrote tests/last_test_output.txt listing the three test ids and \"3 tests collected in 0.01s\", which matches the three tests written. The \"no tests\" in the lane summary is only because collect-only runs nothing. The real run also shows \"collected 3 items\".\n7. Observed, not predicted: yes, now observed. Probe tests/tmp/probe_phase3_seams.py printed: NORMALISED {'': None, '   ': None, '.': None, 'https://': None, 'tube.example.': 'tube.example', 'https://Other.Example/videos': 'other.example', 'https://Tube.Example/': 'tube.example', 'tube.example': 'tube.example'}; SYNC_ONE (1, 0, 1); ROWS_ONE [('tube.example',)]; SYNC_TWO (2, 0, 2); ROWS_TWO [('https://tube.example/',), ('tube.example',)]; JOIN_NOW and SYNC_NOW {'.', 'https://other.example/videos', 'tube.example.', 'https://'}. Every expected value in the test matches these. Lines 48, 49 and 59 are not reached in the checkpoint's red run, so the probe is what grounds them. I have no delete tool, so the probe file is still on disk and needs removing; it is not part of the checkpoint.\n8. Red, not green: yes, it is red. ValidateTests on tests/tmp/test_10_normalise_instance_hosts_phase3.py returned \"[exit status 1]\", \"3 failed\", with \"FFF\" and \"3 failed in 0.04s\".\n9. Red for the right reason: yes. Each failure is a judged assertion showing the jobs do not yet normalise; none is a control, import or path failure. Line 44 failed on \"assert {'https://tub...tube.example'} == {'tube.example'} \u2026 Extra items in the left set: 'https://tube.example/'\". Line 58 failed with extra items 'https://', 'tube.example.', 'https://other.example/videos' and '.'. Line 65 failed with \"Failed: DID NOT RAISE ValueError\". The fixture loaded both job modules (the traceback shows `jobs` bound to both), so the harness works.\n10. Observed expected output: yes, every row's expected value is what a run showed. For lines 44, 58 and 65, the checkpoint run showed today's wrong values and the probe showed the normalised values the rows expect. For lines 48 and 49, the probe's SYNC_ONE and ROWS_ONE match. For line 59, the probe's normalisation values give the expected set, and JOIN_NOW shows the current wrong one. No run contradicted a row, so nothing was rewritten.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `engine/server/db/jobs/sync-whitelist.py`\n- The `data.moderation` import now also brings in `normalize_host_token`.\n- In `fetch_hosts`, each entry is now normalised with `host_value = normalize_host_token(str(host))` instead of `str(host).strip().lower()`. The existing `if host_value:` guard already drops `None`, so entries that normalise to nothing are skipped. When no host is left, the function still raises `ValueError(\"Whitelist contained no hosts.\")`. The User-Agent, error handling and payload-shape handling are unchanged.\n\n### `engine/server/db/jobs/updater-worker.py`\n- `normalize_host_token,` is added to the parenthesised `data.moderation` import, between `list_active_denied_hosts` and `purge_host_data`.\n- `fetch_join_hosts` makes the same swap: `value = normalize_host_token(str(host))`. The existing `if value:` guard drops `None`. `list_prod_hosts` is untouched, as the plan says.\n\n### `tests/active/test_host_normalisation.py`\n- The module docstring has two new bullets covering the job behaviour.\n- New imports: `importlib.util` and `sqlite3`. New constant: `JOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"`.\n- New helpers:\n  - `_load_job` loads a job file with `spec_from_file_location`.\n  - a module-scoped `jobs` fixture loads both jobs.\n  - `_payload_url` writes the payload to `tmp_path` and returns a `file://` URI.\n- Three new durable tests, one for each behaviour this phase delivers:\n  - `test_sync_job_stores_one_spelling_per_host`: a list payload with `https://Tube.Example/` and `tube.example` gives `{\"tube.example\"}`. `sync_hosts` on a temp SQLite database returns `(1, 0, 1)` and stores the single row `tube.example`.\n  - `test_jobs_drop_entries_that_normalise_to_none`: a `{\"data\": [...]}` payload with `\"\"`, `\"   \"`, `\".\"` and `\"https://\"` plus two valid entries gives `{\"tube.example\", \"other.example\"}` from both `fetch_hosts` and `fetch_join_hosts`.\n  - `test_sync_job_still_rejects_a_list_with_no_usable_host`: `fetch_hosts` raises `ValueError` with exactly \"Whitelist contained no hosts.\".\n\n### What I ran\n- I ran `ValidateTests tests/active/test_host_normalisation.py -k job`: 3 passed, 16 deselected, exit 0.\n- I did not run the gating checkpoint. It exercises the same functions on the same inputs.\n- I did not run the post-phase commands the plan lists: test-moderation-integration.py, test-orchestrator-smoke.py and the full validate_tests.py compared with the green baseline. They are still owed, and the smoke test counts as not run if node, dist, the embedding stack or the network is missing.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone. The worktree matches the inlined code, and the only duplication left is older than this build and was not added by it (see left_out).\n</refactors>\n\n<left_out>\n1. Shared entry loop. `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py` and `fetch_join_hosts` in `engine/server/db/jobs/updater-worker.py` have the same payload-shape and entry-normalising loop. Moving it into one helper in `data.moderation` would guarantee C2 (both jobs return the same host set) by construction. I did not do it: the two copies existed before this build, the helper would be a new public function in `moderation.py`, and the two jobs still differ in User-Agent, fetch error text and the \"no hosts\" raise. The gating test already pins that they agree.\n2. `if not host: continue` guard in both loops. It is not redundant and stays: `str(None)` is `\"none\"`, and `normalize_host_token` would keep that as a host.\n3. Return annotation on `sync_hosts`. In sync-whitelist.py it says `tuple[int, int]` but the function returns three values. Fixing it would make the comment \"despite its two-element annotation\" in the gated `test_sync_job_stores_one_spelling_per_host` false, and I cannot edit that test. It is also older than this build.\n4. Probe files. `tests/tmp/` still holds files from earlier turns that I have no tool to delete: probe_host_token.py, probe_git_outside_worktree.py, probe_durable_host.py, probe_phase2_env.py, probe_phase2_harness.py, probe_phase3.py, probe_phase3_seams.py and the test_10_normalise_instance_hosts_phase{1,2,3}.py checkpoint copies. The operator should remove the probes.\n5. Pass criteria. The step's \"What the pass is measured against\" section arrived as the unfilled placeholder `{rat_tail_rules}`, so I checked the pass against the role's rules instead. The one `rat-tail:` comment, in `_whatwg_hostname`, names both its limit and its upgrade path.\n6. Checks still owed from phase 3. test-moderation-integration.py, test-orchestrator-smoke.py and the full validate_tests.py baseline comparison have not been run.\n</left_out>\n\n<needs_fresh_red>\n`engine/server/db/jobs/compare-join-hosts.py:80` also reads the JoinPeerTube hosts list, and it still uses `str(host).strip().lower()`. So it can disagree with the two jobs this build changed, for example by counting `https://Tube.Example/` as its own host. Switching it to `normalize_host_token` changes its output, so it is new behaviour, not a refactor. It needs its own phase and red, and it is outside the files this build approved.\n</needs_fresh_red>\n\n<observation>\nThe worktree matches the inlined code, and `normalize_host_token` has exactly two callers, `fetch_hosts` and `fetch_join_hosts`. No refactor was needed without changing either behaviour or code older than this build.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"DATA_BUILD.md\" update=\"yes\">\nSection \"2) Filter to JoinPeerTube whitelist\". Its \"Notes:\" list (lines 145-149) says where the whitelist comes from and what include and exclude mode do. It says nothing about how entries are turned into hosts, and that is the behaviour this build changed. Add one bullet saying that `sync-whitelist.py`'s `fetch_hosts` passes every entry through `data.moderation.normalize_host_token`, which is a port of the crawler's `normalizeHostToken`, so the job stores the same spelling the crawler does:\n- URL-like entries (`http(s)://\u2026`, or anything containing `/`) keep only the hostname. Scheme, userinfo, port and path are dropped. IPv6 keeps its brackets and IDNs become punycode.\n- Bare entries only have leading and trailing dots trimmed, so a bare `host:port` keeps its port.\n- Entries that normalise to nothing (`\"\"`, `.`, `https://`) are skipped.\n- The job still fails with \"Whitelist contained no hosts.\" if no entry is left.\n\nThe bullet should describe the current state only, with no \"now\" wording.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\" update=\"yes\">\nThe \"What Exactly Is Collected\" bullet on line 59 (\"Instances: from whitelist source (JoinPeerTube URL by default).\") is incomplete. It should say that with `--sync-join-whitelist` the fetched hosts (`fetch_join_hosts`) go through the crawler-equivalent `data.moderation.normalize_host_token` before they are compared with prod hosts and the denylist to work out the new and stale sets. Entries that normalise to nothing are dropped. Stale hosts are purged from the prod and similarity DBs only with `--yes`, and `--dry-run` shows the plan first.\n\nAlso state, without \"previously\" wording, that `instances` rows stored under a spelling other than the crawler's (for example with a scheme or trailing dots) show up as stale. Operators should review with `--dry-run` before passing `--yes`.\n\nThe \"Important Flags\" list (lines 101-115) has `--whitelist-url` but leaves out `--sync-join-whitelist`, `--yes` and `--dry-run`, which this behaviour depends on. Add them.\n</doc>\n<doc path=\"docs/project/issues/06-normalise-instance-hosts.md\" update=\"yes\">\nChanges at harvest:\n- Tick the acceptance criteria. The table-driven Python test, the Node check against `dist/host-filters.js` over the shared `tests/active/host_tokens.json` fixture, the one-spelling sync, None entries dropped, and `fetch_join_hosts` == `fetch_hosts` are all delivered by `tests/active/test_host_normalisation.py`.\n- The criterion \"Existing moderation-integration and orchestrator smoke tests pass\" may only be ticked once those standalone runs have actually happened. The build left them owed, along with the full `validate_tests.py` baseline comparison.\n- Set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.\n- Record where the helper landed: `normalize_host_token` in `engine/server/data/moderation.py`, next to the unchanged `normalize_host`.\n- Record the dist-staleness rule: git commit times, with an mtime fallback when src is dirty or a file has no history. A missing node, dist or git fails the test and never skips it.\n- Record the accepted limitations:\n  - Branch 4 keeps `@ ? #` and ports.\n  - Parity is proven only for the fixture inputs and on the interpreter that runs the test. The `rat-tail` note covers forbidden host code points, and IDNA 2003 vs UTS #46.\n  - `compare-join-hosts.py` still uses strip/lower.\n  - The crawler's `--whitelist-file` read-back strips dots from URL-form hosts that end in a dot.\n  - `normalize_host` (denylist) does not bracket IPv6 or convert to punycode.\n  - Existing rows are not rewritten.\n</doc>\n<doc path=\"docs/project/plans/10-normalise-instance-hosts.md\" update=\"yes\">\nAt harvest, mark the plan delivered and point to the build plan `docs/project/plans/16-10-normalise-instance-hosts.md`. Its \"Requirement: existing scripts and suite still pass\" paragraph is now wrong: it says the smoke test \"serves `whitelist.json` through `fetch_hosts`\". Correct it to `fetch_join_hosts`, which the smoke test reaches through `updater-worker.py --whitelist-url`. Also note:\n- Only `sync-whitelist.py` parses `schema.sql` at import.\n- The updater's hosts file is not always a fixed point when the crawler reads it back. Dotted URL-form hosts change.\n- The fixture holds 15 pairs, not 14. `https://tube.example./` \u2192 `tube.example.` was added.\n- Fail-loudly was chosen over build-first, with the git-based staleness rule.\n- Harvest should move the plan to `plans/archive/`, as delivered plans are.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"yes\">\nAdd follow-up lines, all outside this build. The M6 moderation section or the security remainder is the natural home.\n- Move `compare-join-hosts.py` (`hosts_from_payload` and `load_local_hosts`) onto `normalize_host_token`. It is now the only Python reader of the JoinPeerTube list that still uses strip/lower, and it can report hosts as missing when the jobs treat them as present.\n- Make the crawler's `--whitelist-file` mode (`loadHostsFromFile`, where branch 4 strips dots) agree with its URL mode (which keeps the WHATWG trailing dot), so that dotted entries stop churning through purge and recrawl.\n- Optionally, align `normalize_host` (denylist input) on bracketed IPv6 and punycode, so denylist entries match the join-host spelling.\n\nAt harvest, issue 06 closes. The M1 line \"Open security issues: `01` to `07`\" and step 1 of \"Implementation order\" (`04`, `05`, `06`) must stop listing 06 as open, and \"Delivered\" gains a line for issue 06 that points at the archived plan.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"no\">\nIt mentions `sync-whitelist.py` only in the run-order warning on line 43: run it after `crawl:videos` completes. It says nothing about how hosts-list entries are parsed or normalised, and that ordering is unchanged.\n</doc>\n<doc path=\"README.md\" update=\"no\">\nLine 14 says only that filtering keeps instances that appear in the JoinPeerTube whitelist. That is still true, and the README makes no claim about entry spelling.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md\" update=\"no\">\nIt describes the smoke test's inputs (`test-instances.json` or prod rows) and flow, and makes no claim about host normalisation or which fetch function is used. Its plain lowercase hosts pass through `normalize_host_token` unchanged, so nothing it says has become false.\n</doc>\n<doc path=\"docs/project/security-audit/run-2/REPORT.md\" update=\"no\">\nThis is a point-in-time audit record, not living documentation. Its line saying the moderation layer normalises hosts through `normalize_host` before comparing or deleting is still true: purges and serving filters still use `normalize_host`. The finding SI4-M1 is closed through the issue file, not by editing the report.\n</doc>\n<doc path=\"docs/project/adr/0001-derived-interaction-event-ids.md\" update=\"no\">\nIt covers interaction event ids. It does not touch host normalisation or the whitelist jobs. The same holds for ADRs 0002 (trusted proxy client address), 0003 (metadata endpoint uuid entries), 0004 (CORS) and 0005 (raw event retention). None of them makes a claim about JoinPeerTube host parsing.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:DATA_BUILD.md": "<changes>\nDATA_BUILD.md step 2 \"Notes:\" now has a bullet on how `sync-whitelist.py` turns whitelist entries into hosts through `normalize_host_token`.\n\n- The new bullet sits after the `--mode exclude` line. It says every entry goes through `data.moderation.normalize_host_token`, a port of the crawler's `normalizeHostToken`, so the job stores the same spelling the crawler does.\n- It has three sub-bullets:\n  - URL-like entries (`http://`, `https://`, or anything containing `/`) keep only the hostname, lowercased. Scheme, userinfo, port and path are dropped, IPv6 keeps its brackets, and internationalised names become punycode.\n  - Bare entries are lowercased and only have leading and trailing dots trimmed, so a bare `host:port` keeps its port.\n  - Entries that normalise to nothing (`\"\"`, `.`, `https://`) are skipped, and the job fails with \"Whitelist contained no hosts.\" when no entry is left.\n- I checked each claim against the code: `normalize_host_token` and `_whatwg_hostname` in `engine/server/data/moderation.py`, and `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py`.\n- The bullet describes only how things work today, with no \"now\" or \"previously\" wording. It says nothing about the updater, the fixture or the limitations, because other documents on this checklist cover those.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/db/jobs/docs/UPDATER_WORKER.md": "<changes>\nUPDATER_WORKER.md now explains how `--sync-join-whitelist` normalises hosts, when it purges stale hosts, and the `--yes`/`--dry-run` flags that control that.\n\nI checked each claim against `updater-worker.py` (the argparse block, `fetch_join_hosts`, `list_prod_hosts`, `purge_hosts` and the sync block in the main run).\n\n- **\"What Exactly Is Collected\"**: the Instances bullet now has sub-bullets.\n  - **Default mode:** `instances-cli` reads `--whitelist-url` itself.\n  - **With `--sync-join-whitelist`:** `fetch_join_hosts` sends each entry through `data.moderation.normalize_host_token`, which gives the same spelling as the crawler's `normalizeHostToken`. Entries that normalise to nothing (`\"\"`, `.`, `https://`) are dropped and denylisted hosts are removed. What remains is compared with the prod `instances` hosts: new hosts are crawled through `instances-cli --whitelist-file`, and prod hosts not on the list are stale.\n  - **Purge:** stale hosts are purged from the prod and similarity DBs only with `--yes`. If stale hosts exist and `--yes` is missing, the worker refuses to run. `--dry-run` logs the stale hosts and the delete plan, then exits without changing anything.\n  - **Old spellings:** prod hosts are only trimmed and lowercased before the comparison (`list_prod_hosts`). So an `instances` row stored in a spelling the crawler never produces (a scheme, trailing dots) counts as stale and `--yes` purges it. Operators should review with `--dry-run` first. This is written as current behaviour, with no \"previously\" wording.\n- **\"Important Flags\"**: added `--sync-join-whitelist`, `--yes` and `--dry-run`, each with a short description based on its argparse help.\n\nI left one existing inaccuracy alone because it is outside this build's scope: step 3 of \"Execution Order\" says staging is seeded from prod unless `--resume-staging` is used, but the code also skips seeding under `--sync-join-whitelist`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/06-normalise-instance-hosts.md": "<changes>\nIssue 06 is marked delivered: status is `bug, complete`, five of the six acceptance criteria are ticked, and a delivery comment is added. The file has not been moved to `archive/` yet because I have no tool that can move or delete files.\n\n- **Status line:** `Status: bug, ready-for-agent` is now `Status: bug, complete`.\n- **Acceptance criteria:** I ticked the five that `tests/active/test_host_normalisation.py` covers:\n  - the table-driven port test;\n  - the node check of the crawler's compiled `dist/host-filters.js` over `host_tokens.json`;\n  - the sync job storing one spelling per host;\n  - entries that normalise to None being dropped;\n  - `fetch_join_hosts` returning the same set as `fetch_hosts`.\n- **Criterion left open:** \"Existing moderation-integration and orchestrator smoke tests pass\" stays unticked. The build never ran those two scripts, and the test-output files record no run of them either.\n- **Delivery comment:** added under `## Comments`, after the triage comment. It records:\n  - it links to the archived plan `docs/project/plans/archive/10-normalise-instance-hosts.md` and the build plan `docs/project/plans/16-10-normalise-instance-hosts.md`;\n  - the helper is `normalize_host_token` in `engine/server/data/moderation.py`, right after the unchanged `normalize_host`, with the private `_whatwg_hostname` handling URL-form entries, and both jobs switched from `strip().lower()` to it;\n  - the test file and its fixture, which holds the 14 required inputs plus `https://tube.example./` \u2192 `tube.example.`;\n  - the stale-build rule: a missing node, dist or git fails the test and never skips it. It compares git commit times, and falls back to file times when a file has uncommitted edits or no commit;\n  - that the two standalone scripts and the full `validate_tests.py` comparison against the baseline are still owed;\n  - the six accepted limitations. I checked each against `moderation.py`, the `rat-tail` comment and `host-filters.ts`, where `loadHostsFromFile` sends every line through `normalizeHostToken`.\n- **Still to do at harvest:**\n  - Move the file to `docs/project/issues/archive/06-normalise-instance-hosts.md`, as `docs/project/issue-tracker.md` requires. Use `git mv`, from an agent that has a shell.\n  - The comment's link assumes plan 10 is moved to `plans/archive/`, which that plan's own checklist item asks for.\n  - Tick the last criterion only once both standalone scripts pass.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/plans/10-normalise-instance-hosts.md": "<changes>\nI marked plan 10 as delivered, pointed it at build plan 16, and added a \"Delivery\" section recording what the build settled and three corrections to the plan's reading of the code. I did not move the file to `plans/archive/`, because I have no tool that can move files.\n\n- **Status line** (new, under the title): says the plan is delivered by `docs/project/plans/16-10-normalise-instance-hosts.md` (wave 1). It points to the issue for the accepted limitations and the checks still owed, and does not repeat them.\n  - The issue link uses the archive path `docs/project/issues/archive/06-normalise-instance-hosts.md`. That matches the issue's own delivery comment, which links to this plan at `plans/archive/`. Both links only work once harvest moves both files.\n- **Risks and limitations:** the dist bullet no longer says \"the build chooses which at its checkpoint\". It now says the test fails loudly, never skips and never builds, and points to \"Delivery\".\n- **New \"Delivery\" section.** Every claim was checked against the code:\n  - **What the build settled:**\n    - The fixture has 15 pairs, not 14. `https://tube.example./` \u2192 `tube.example.` was added, and I confirmed it in `tests/active/host_tokens.json`.\n    - The test fails loudly instead of building first. It fails, and never skips, when node, dist or git is missing or dist is stale. The staleness check compares git commit times; I confirmed this in `_dist_is_stale` and `test_crawler_dist_returns_pinned_values`. The rest of the rule is left to the issue, which owns it.\n  - **Corrections:**\n    - The smoke test reaches `fetch_join_hosts` through `updater-worker.py --whitelist-url`, not `fetch_hosts`. I checked this in `test-orchestrator-smoke.py` (lines 421 and 440) and at `updater-worker.py:831`.\n    - Only `sync-whitelist.py` parses `schema.sql` when it is imported. The updater reads it inside `main()` (line 789).\n    - When the crawler reads back the `--whitelist-file` hosts, it strips a trailing dot from URL-form hosts. I checked this against `loadHostsFromFile` in `host-filters.ts` and `updater-worker.py` lines 894\u2013916. This section links to the roadmap for the follow-up.\n- **Not in this file:** the checklist asks me to fix a sentence in the \"Requirement: existing scripts and suite still pass\" paragraph, the one saying the smoke test \"serves `whitelist.json` through `fetch_hosts`\". That sentence is not in plan 10. It is at line 164 of the build plan `docs/project/plans/16-10-normalise-instance-hosts.md`, which is not on the checklist, and I left it unchanged. Plan 10 now carries the correct fact under \"Corrections\".\n- **Still to do at harvest:** `git mv` this file to `docs/project/plans/archive/10-normalise-instance-hosts.md`, as is done for delivered plans.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/roadmap.md": "<changes>\nRoadmap: issue 06 moved to Delivered, dropped from the open-security lists, and three host-normalisation follow-ups added under M6.\n\n- **Delivered**: a new line for security issue `06`. `sync-whitelist.py` and the updater's `fetch_join_hosts` both pass every hosts-list entry through `data.moderation.normalize_host_token`, a port of the crawler's `normalizeHostToken`. The line points at `docs/project/plans/archive/10-normalise-instance-hosts.md`, where harvest moves the plan.\n- **M1**: \"Open security issues\" now reads `01` to `05` and `07`.\n- **Implementation order, step 1**: now reads `01`, `02`, `03`, then `04`, `05`. Issue `06` is no longer listed.\n- **M6**: three follow-up lines, each checked against the code:\n  - Move `compare-join-hosts.py` onto `normalize_host_token`. Its `hosts_from_payload` (line 80) and `load_local_hosts` (line 96) still use `strip().lower()`.\n  - Make the crawler's `--whitelist-file` mode (`loadHostsFromFile`, `host-filters.ts:10`, which calls `normalizeHostToken`) agree with URL mode on trailing dots.\n  - Optionally, align `normalize_host` (denylist input) on bracketed IPv6 and punycode.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>"
  },
  "requirements": "### What is being built\n\nIssue `docs/project/issues/06-normalise-instance-hosts.md` (plan `docs/project/plans/10-normalise-instance-hosts.md`, security hardening batch wave 1), category bug. The work is an exact Python port of the crawler's `normalizeHostToken` (`engine/crawler/src/host-filters.ts`, the exported function near line 83). The two Python readers of the JoinPeerTube hosts list will use it: `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py` (function at about line 219, the `str(host).strip().lower()` at about line 243) and `fetch_join_hosts` in `engine/server/db/jobs/updater-worker.py` (function at about line 414, the `strip().lower()` at about line 438). Once earlier waves merge, line numbers will drift, so find these by function name.\n\n### Purpose\n\nThree components read the same JoinPeerTube hosts list: `sync-whitelist.py`, `updater-worker.fetch_join_hosts`, and the TypeScript crawler. Only the crawler normalises. As a result one entry can be stored under two spellings, and the updater gets new/stale host sets wrong and misses denylist matches. After this build, both Python jobs produce the same string as the crawler for the same entry. That closes audit finding SI4-M1 (task 86) as far as the triage decision allows: an exact port, with no validation beyond what `normalizeHostToken` does.\n\n### The helper\n\n- `normalize_host_token(value: str) -> str | None`, with a docstring, in a module of the Engine's shared `engine/server/data` package. Both jobs already put `engine/server` on `sys.path` and import `data.moderation`. Whether it goes in a new module or an existing one is a design decision for the next step. Fewest files is preferred. It must not change `data.moderation.normalize_host`.\n- It returns exactly what `normalizeHostToken` returns for the same input:\n  1. `value.strip().lower()`. If that is empty, return None.\n  2. If it starts with `http://` or `https://`, parse it as a URL and return the hostname, lowercased. Return None if the hostname is empty or parsing fails.\n  3. Else, if it contains `/`, parse `https://` + value and return the hostname, lowercased. Return None if the hostname is empty or parsing fails.\n  4. Else, return the value with every leading and trailing `.` removed, or None if nothing is left. No URL parse happens in this branch, so ports, `@`, `?`, `#` and non-ASCII characters are kept as they are.\n- In branches 2 and 3 the Python parser (stdlib `urllib.parse`, no new dependency) must match the WHATWG `URL.hostname`:\n  - userinfo is dropped (`user@host` \u2192 `host`)\n  - the port is dropped\n  - IPv6 literals keep their brackets: `urlparse(...).hostname` returns `::1` and the crawler returns `[::1]`\n  - internationalised names are returned as punycode (`b\u00fccher.example` \u2192 `xn--bcher-kva.example`)\n  - input WHATWG rejects returns None\n- Branch 4 does no punycode conversion, matching the crawler.\n\n### Pinned expected values\n\nThese inputs go into one JSON fixture of input \u2192 expected pairs that both the Python and the Node side read. Expected values are the WHATWG results; the Node check confirms them against the crawler's real output:\n- `\" Tube.Example \"` \u2192 `\"tube.example\"`\n- `\"tube.example.\"` \u2192 `\"tube.example\"`\n- `\"..tube.example..\"` \u2192 `\"tube.example\"`\n- `\"https://Tube.Example/\"` \u2192 `\"tube.example\"`\n- `\"http://tube.example:8080/path\"` \u2192 `\"tube.example\"`\n- `\"https://user@tube.example\"` \u2192 `\"tube.example\"`\n- `\"tube.example/videos\"` \u2192 `\"tube.example\"`\n- `\"tube.example:9000\"` \u2192 `\"tube.example:9000\"` (branch 4, the port is kept)\n- `\"https://[::1]:8080/\"` \u2192 `\"[::1]\"`\n- `\"https://b\u00fccher.example/\"` \u2192 `\"xn--bcher-kva.example\"`\n- `\"\"` \u2192 null\n- `\"   \"` \u2192 null\n- `\".\"` \u2192 null\n- `\"https://\"` \u2192 null (WHATWG throws; the crawler returns null)\n\nThe fixture may grow; every input in it must pass on both sides.\n\n### Job changes\n\n- `fetch_hosts` (sync-whitelist) and `fetch_join_hosts` (updater) each replace `str(host).strip().lower()` with `normalize_host_token(str(host))` and skip entries that return None. Nothing else changes in either function: the fetch, the payload shape handling (`{\"data\": [...]}` or a list, with `host` taken from dicts), the User-Agent strings, the error types and messages.\n- `fetch_hosts` still raises `ValueError(\"Whitelist contained no hosts.\")` when no entry survives. That is existing behaviour. \"The job still completes\" means a payload in which some entries return None.\n- `list_prod_hosts`, `load_denied_hosts`, `compare-join-hosts.py`, `data.moderation.normalize_host`, the denylist/moderation CLIs and all crawler code stay unchanged.\n\n### Acceptance criteria\n\n- A table-driven Python test asserts `normalize_host_token` against every fixture pair.\n- The same test runs Node on the crawler's compiled `engine/crawler/dist/host-filters.js`, calling its exported `normalizeHostToken` over the same fixture inputs, and asserts that its output equals the fixture's expected value, and so equals the Python output. `dist/host-filters.js` is present in this worktree and its `normalizeHostToken` matches `src/host-filters.ts`.\n  - If `node` is missing, or `dist` is missing or older than `src/host-filters.ts`, the test must fail loudly, never skip, or it builds first. The build checkpoint chooses which.\n  - `engine/crawler/node_modules` (and so `tsc`) is not guaranteed in a fresh worktree, so the fail-loudly option does not depend on it.\n- Given a hosts payload containing `\"https://Tube.Example/\"` and `\"tube.example\"`, the whitelist sync job's host fetch returns the single host `tube.example`, which the job then stores through `sync_hosts`. The payload can be served from a local stdlib HTTP server or a `file://` URL, as `test-orchestrator-smoke.py` already serves `whitelist.json`.\n- Entries for which the helper returns None (for example `\"\"`, `\".\"`, `\"https://\"`) are not in either job's host set, and the fetch completes as long as at least one entry survives.\n- `fetch_join_hosts` returns, for the same payload, the same set as `fetch_hosts`.\n- The existing standalone scripts `engine/server/db/jobs/tests/test-moderation-integration.py` and `engine/server/db/jobs/tests/test-orchestrator-smoke.py` still pass. They are not part of `validate_tests.py`'s `tests/active` suite and are run separately.\n- The `tests/active` suite still passes through `validate_tests.py`.\n\n### Tests: placement and running\n\n- The new test is a pytest file in `tests/active` (the active tree; the working tree is `tests/tmp`, the archive `tests/archive`). Its JSON fixture sits beside it or in another path both sides can read. The job scripts have hyphenated filenames, so the test loads them with `importlib` (spec from file location), as they cannot be imported normally.\n- The new test needs no Engine, so the Engine rate-limit rule, which says Engine-backed files run in their own `validate_tests.py` invocations, does not apply to it. It still applies to the Engine-backed files already in `tests/active`.\n- Run `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts`, the `project_dir` in this worktree's `.un/skills/devsecops/config.json`. The record is `tests/last_test_validation.json` and the output `tests/last_test_output.txt`.\n- Adding a `test_groups` entry mapping the new test file to the helper module and the two job files happens at harvest on main, not in this worktree.\n\n### Baseline suite state\n\nBefore the build the suite ran green: exit code 0, variant false. Any red after the build was introduced by the build.\n\n### Style and constraints\n\n- New code follows the file it lands in:\n  - `\"\"\"Handle ...\"\"\"`-style or descriptive one-line docstrings\n  - `from __future__ import annotations` where the module already uses it\n  - module-level named constants\n  - stdlib only\n  - one statement or comment per line, no softwrapping\n- No new dependency. No interface with only one implementation.\n- Backwards compatibility is not required beyond what is stated here.\n\n### Out of scope\n\n- Changing `normalizeHostToken` or any crawler behaviour.\n- Any validation stricter than `normalizeHostToken`: IP literals, ports, userinfo, characters.\n- Rewriting host rows already stored in `instances`.\n- `data.moderation.normalize_host` and the denylist/moderation CLIs.\n- `compare-join-hosts.py`.\n- The orchestrator smoke test's own `strip().lower()` host reader.\n\n### Known limitations, accepted\n\n- An entry with no scheme and no `/` goes through branch 4 and is stored almost as given. So `evil@tube.example`, `host?x`, `host#y` and `tube.example:9000` are stored with those characters. The audit's `/ ? # @` concern is closed only for entries that go through the URL branches. This follows from the settled exact-port decision; the operator accepted it.\n- `urllib.parse`/`idna` and WHATWG may still differ on inputs outside the fixture:\n  - percent-encoding and backslashes\n  - IDNA 2003 (Python's `idna` codec) versus UTS #46 (WHATWG), for example `\u00df`\n  - JS `trim()` versus Python `strip()` on characters such as U+FEFF and U+001C-U+001F\n  - `toLowerCase()` versus `lower()` on characters such as `\u0130`\n  - Only the fixture inputs are pinned. The upgrade path is to add inputs to the fixture; the Node check then shows any mismatch.\n- `data.moderation.normalize_host`, used for denylist input, returns IPv6 without brackets and does not convert to punycode. A denylist entry for an IDN or IPv6 host may therefore not match the new spelling. This is out of scope.\n- Hosts already stored under the old spelling are not rewritten, so one updater run after the change may treat the old and new spellings as different hosts.\n- The Python test depends on Node and on the crawler's compiled `dist` being present and current.\n\n### Batch and worktree context\n\n- Wave 1 of the security hardening batch (`.scratch/security-hardening-batch/notes.md`), in worktree `.worktrees/fix-10-normalise-instance-hosts`. The build touches no file another batch issue touches: 05 and 02 edit `engine/server/data/interaction_events.py`, `similar.py` and others, not the files above.\n- `whitelist.db` is symlinked to the main tree and shared with other lanes. The new test does not touch it.\n- When merging, the tracked `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n- Harvest happens on main after the merge.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\n**Where the helper goes.** `normalize_host_token` goes into the existing `engine/server/data/moderation.py`, placed directly after `normalize_host`. That module is already the shared place for host normalisation (its header comment lists it). Both jobs already import from it: `sync-whitelist.py` has a single-line `from data.moderation import ...` and `updater-worker.py` has a parenthesised import. It already imports `urlparse` and uses `from __future__ import annotations`. So the port needs no new file, and each job only adds one name to an import it already has. The new function's docstring follows the file's descriptive one-line style. It must state that the function is an exact port of the crawler's `normalizeHostToken` and differs from `normalize_host` (which is left untouched), so a later reader does not merge the two. Any constants go at module level.\n\n**How the helper works.** It follows the four branches of `normalizeHostToken` (`engine/crawler/src/host-filters.ts:83`) in the same order:\n1. Strip and lowercase the input. If the result is empty, return None.\n2. If it starts with `http://` or `https://`, parse it as a URL and derive the WHATWG-style hostname.\n3. Else, if it contains `/`, parse `https://` + value and derive the hostname the same way.\n4. Else, return the value with leading and trailing dots stripped, or None if nothing is left.\n\nBranch 4 never calls the parser. That keeps `tube.example:9000` as it is and does no punycode conversion, as the crawler does.\n\n**Deriving the hostname in branches 2 and 3.** One private step turns `urllib.parse.urlparse` output into the value WHATWG `URL.hostname` would give:\n- **Userinfo and port.** `.hostname` already drops userinfo and the port and lowercases the host.\n- **Port validity.** The step also reads `.port`. Python raises ValueError on a port that is non-numeric or above 65535, which is input WHATWG also rejects. This costs one attribute read.\n- **Empty host.** If the host is missing (`https://`), return None, as the crawler does when `new URL` throws.\n- **IPv6 literals.** `.hostname` returns `::1` without brackets. When the host contains `:`, pass it through stdlib `ipaddress.IPv6Address`. That validates it (invalid gives None, like a WHATWG throw) and gives the compressed form WHATWG serialises. Then put the brackets back, giving `[::1]`. Unbalanced brackets make `urlparse` itself raise ValueError, which becomes None.\n- **Internationalised names.** If the host is not ASCII, encode it with the stdlib `idna` codec to get punycode (`xn--bcher-kva.example`). A UnicodeError becomes None. ASCII hosts are not sent through the codec. The codec rejects empty labels and labels over 63 characters, which WHATWG accepts for ASCII names (`https://a..b/` gives `a..b`), so running ASCII hosts through it would add rejections the crawler does not make.\n- **Errors.** ValueError and UnicodeError are caught around the parse, the same way the crawler's `try/catch` wraps its whole body.\n\n**Requirement: both jobs use it.** In `fetch_hosts` (`sync-whitelist.py`, the `strip().lower()` line inside the entry loop) and in `fetch_join_hosts` (`updater-worker.py`, the same line), that expression is replaced with `normalize_host_token(str(host))`. The following `if host_value:` / `if value:` guard already skips None, so the loop needs no other change. The fetch, the User-Agents, the payload-shape handling and the error messages stay the same. `fetch_hosts` still raises `ValueError(\"Whitelist contained no hosts.\")` when no entry survives. `list_prod_hosts` (the other `strip().lower()` in the updater, at about line 449) is deliberately left alone.\n\n**Requirement: the fixture and the table-driven test.** A new pytest file in `tests/active` (working name `test_host_normalisation.py`), with a JSON fixture beside it (`host_tokens.json`). The fixture is a list of `{input, expected}` pairs holding the 14 pinned values, with null for None. The test has three parts:\n- **Python side.** A parametrised test asserts `normalize_host_token(input) == expected` for every pair. It imports the helper after adding `engine/server` to `sys.path`, as the jobs do.\n- **Node side.**\n  - It runs `node --input-type=module` once, with a short inline script. The script imports `engine/crawler/dist/host-filters.js` by `file://` URL, reads the fixture inputs as JSON on stdin, maps them through `normalizeHostToken` and prints JSON on stdout.\n  - The Python test then asserts that each Node result equals the expected value. Together with the Python-side assertions, that also proves Python output equals crawler output.\n  - `dist/host-filters.js` imports only `node:fs`, and the crawler package is `\"type\": \"module\"`, so no `node_modules` is needed.\n- **Job side.**\n  - Both job files are loaded with `importlib.util.spec_from_file_location`. Their top-level code only sets up `sys.path` and parses `engine/crawler/schema.sql`, and `main()` sits behind `__name__` guards, so loading them has no side effects.\n  - A payload is written to `tmp_path` and served as a `file://` URL. `urlopen` handles `file:` even with a `Request` that carries headers, so no server thread is needed.\n  - One test checks that `[\"https://Tube.Example/\", \"tube.example\"]` gives `{\"tube.example\"}` from `fetch_hosts`. It then stores that set through `ensure_whitelist_schema` + `sync_hosts` into a temporary SQLite file (never the shared `whitelist.db`) and checks the stored row.\n  - A second test mixes `\"\"`, `\".\"`, `\"https://\"` with valid entries. It asserts the invalid entries are absent, the fetch completes, and `fetch_join_hosts` returns the same set as `fetch_hosts`. It uses the dict shape (`{\"data\": [{\"host\": ...}]}`) so both payload shapes are covered.\n  - The file uses no Engine fixture, so it runs in the normal `validate_tests.py` pass.\n\n**Requirement: loud failure, never skip.** Before the Node call, the test fails with `pytest.fail` and a message naming the fix in three cases:\n- `node` is not on PATH (found via `shutil.which`)\n- `dist/host-filters.js` is missing\n- `dist` is stale\n\nI recommend fail-loudly over build-first. Building needs `engine/crawler/node_modules/typescript`, which a fresh worktree does not have, so build-first would add a second failure mode and would also write to the tree during a test run. The build checkpoint makes the final choice.\n\n**Requirement: existing scripts and suite still pass.** After the build, run `test-moderation-integration.py` and `test-orchestrator-smoke.py` separately. Then run `validate_tests.py` from the worktree's `project_dir` and compare against the green baseline. The smoke test serves `whitelist.json` through `fetch_hosts`. Its plain hosts come out of the new helper unchanged, so its expectations still hold.\n\n### Alternatives considered\n\n- **New module (`data/hosts.py`) instead of `moderation.py`.** It would keep the file's name tied to moderation, but it adds a file and a second import line in each job. The requirements prefer the fewest files, and `moderation.py` already owns host normalisation. Rejected. The cost: at harvest, the `test_groups` entry maps the new test to all of `moderation.py`, so edits to that module will also trigger this test. That is cheap because the test needs no Engine.\n- **Porting the WHATWG host parser by hand, or adding a dependency such as `idna` or a WHATWG URL library.** Either would match the crawler on more inputs. Hand-porting is a large amount of code for inputs the list does not contain, and a dependency is ruled out. Rejected in favour of `urlparse` plus the small fixes above, with the fixture as the safety net.\n- **Producing the expected values with Node at test time instead of pinning them.** That would make the crawler the only oracle, and a crawler regression would pass silently. The settled design pins the WHATWG values and checks both sides against them. Kept.\n- **Checking whether `dist` is stale by modification time (mtime).** See the risks below. The recommended alternative is git-based: `dist` is stale when `src/host-filters.ts` has uncommitted changes, or when its last commit is newer than the last commit of `dist/host-filters.js`. Use mtime only when the files are untracked. This avoids false failures after a checkout while still catching a source edit that was never rebuilt.\n- **Sending ASCII hosts through the `idna` codec too.** Rejected. It would add rejections (empty or over-long labels) that WHATWG does not make for ASCII hosts.\n\n### Gotchas and risks\n\n- **An mtime-only staleness check breaks fresh clones.** `dist` appears to be tracked in git (no ignore rule). Git writes files in index order, and `dist/` sorts before `src/`, so a fresh checkout usually leaves `dist/host-filters.js` a few milliseconds *older* than `src/host-filters.ts`. A plain \"dist older than src\" check would then fail on a clean tree whose contents match. Hence the git-based rule recommended above. The build checkpoint should settle the rule explicitly, because \"older than\" in the requirements does not say how age is measured.\n- **The Node side runs the compiled `dist`, not `src`.** Parity is only as good as `dist` being current, which is why the staleness check exists.\n- **IDNA 2003 versus UTS #46.** Python's `idna` codec is IDNA 2003 and WHATWG uses UTS #46 (for example `\u00df` maps to `ss` in Python but `xn--zca` in WHATWG). This is accepted and not pinned. Adding such an input to the fixture would make the test fail by design.\n- **IPv4 shorthand.** WHATWG rewrites forms such as `0x7f.1` or `127.1` to `127.0.0.1`. `urlparse` does not. Not pinned, and accepted under the \"outside the fixture\" limitation.\n- **Forbidden host characters.** WHATWG rejects hosts containing characters such as a space, `<`, `>` or `^`. `urlparse` accepts them. A single module-level set of forbidden host code points could close this. I leave it out as speculative, and it can be added the first time a fixture input exposes the gap. This is a deliberate simplification: the ceiling is non-parity on such inputs, and the upgrade is that one constant and a check.\n- **Percent-encoding and backslashes**, JS `trim()` versus Python `strip()`, and `toLowerCase()` versus `lower()` differ as listed in the accepted limitations. None is in the fixture.\n- **Import side effects.** Loading `sync-whitelist.py` through importlib parses `schema.sql` at import time. If that file moves, the test errors on import rather than failing an assertion, which is at least loud.\n- **Merge conflicts.** The tracked `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict on merge. Take main's copy and re-run `validate_tests.py --compare`, as stated in the requirements.\n\n### Tradeoffs the operator is asked to accept\n\n- **Parity is proven only for fixture inputs.** Parity on other inputs is best effort from `urlparse` + `ipaddress` + `idna`. The upgrade path is to add inputs to the fixture.\n- **The test suite gains a hard dependency on `node` and a current `dist`.** When either is missing the test fails rather than skips, as required.\n- **The helper sits next to a similarly named `normalize_host` with different behaviour.** The two are told apart only by name and docstring.\n- **Branch 4 stores `@`, `?`, `#` and port suffixes as given, and existing rows are not rewritten.** The first updater run after the change may treat an old spelling and its new spelling as different hosts. Both points are already accepted in the requirements.",
  "conflicts": "none",
  "impacts": "\n<impact path=\"engine/server/data/moderation.py\" element=\"new normalize_host_token() and its private hostname step, placed after normalize_host (lines 39-63); module imports (lines 14-18); header comment (lines 5-11)\">\n**What changes.** A new public `normalize_host_token(value: str) -> str | None` goes directly after `normalize_host`, with one private helper that turns `urlparse` output into what WHATWG `URL.hostname` would give. The imports gain stdlib `ipaddress`. `urlparse` is already imported (line 18) and `from __future__ import annotations` is at line 3. Any constants go at module level. The header comment's \"host normalization\" bullet (line 9) may name both normalisers so the split is visible.\n\nDocstring style in this file is one-line and descriptive (e.g. line 40, `\"\"\"Normalize host input (lower, strip protocol/path, trim dots/spaces).\"\"\"`), with `\"\"\"Handle ...\"\"\"` on private helpers (lines 323, 340). The new docstring must say the function is an exact port of the crawler's `normalizeHostToken` and differs from `normalize_host`.\n\nReference behaviour, checked against `engine/crawler/src/host-filters.ts:83-100`:\n- `raw = value.trim().toLowerCase()`; empty \u2192 null\n- starts with `http://` or `https://` \u2192 `new URL(raw).hostname.toLowerCase() || null`\n- contains `/` \u2192 `new URL(\"https://\" + raw).hostname.toLowerCase() || null`\n- otherwise `raw.replace(/^\\.+|\\.+$/g, \"\") || null`\n- the whole body is inside try/catch \u2192 null\n\n**What depends on it.**\n- The two job call sites (entries below) and the new test.\n- The module is imported at Engine startup (`engine/server/api/server.py:97`) and by `engine/server/data/serving_moderation.py:11`.\n- It is also imported by `instance-denylist-cli.py:21`, `channel-moderation-cli.py:23`, `compare-join-hosts.py:23`, `sync-whitelist.py:26`, `updater-worker.py:27` and `jobs/tests/test-moderation-integration.py:31`. A syntax or import error here therefore takes down the Engine and every job, not just the two callers.\n\n**Regression risk: medium.** Adding a function changes no existing caller, but getting parity right has pitfalls:\n1. `urlparse('https://[::1]:8080/').hostname` gives `::1`, so the brackets must be put back. Only a host containing `:` is treated as IPv6, because `.hostname` never keeps the port.\n2. Non-ASCII hosts go through `.encode(\"idna\").decode(\"ascii\")`. That raises UnicodeError (a ValueError subclass) on invalid labels, and it must be caught. ASCII hosts must NOT go through the codec, because it rejects empty or over-63-character labels that WHATWG accepts.\n3. `.port` raises ValueError for a non-numeric port or one above 65535, so it must be read inside the try.\n4. `urlsplit` behaviour varies with the CPython version: bracketed-host validation and stripping of leading C0 characters and spaces changed in 3.11.4/3.12. Parity is proven only on the interpreter that runs the test, which may not be the job runtime (docs use `./venv/bin/python3`).\n5. `ipaddress.IPv6Address` accepts scope ids (`fe80::1%eth0`) that WHATWG rejects. This is outside the fixture and accepted.\n6. Branch 4 strips only `.` (`str.strip(\".\")`) after the initial strip/lower and never calls the parser.\n7. The WHATWG hostname returned by branches 2 and 3 keeps a leading or trailing dot (`https://tube.example./` \u2192 `tube.example.`), and so does `urlparse`. The port must NOT strip it. Stripping would break exact parity (see the host-filters read-back entry).\n\nThe Engine imports this module at startup, so the new code must do no module-level work beyond defining constants.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"normalize_host() (lines 39-63), unchanged, and its callers purge_host_data (162), purge_similarity_for_host (199), collect_similarity_host_stats (250), _row_host (414)\">\n**What changes.** Nothing. The requirements forbid touching it.\n\n**What depends on it.**\n- The denylist and channel CLIs (`instance-denylist-cli.py:145`, `channel-moderation-cli.py:78`).\n- The updater's stale-host purge: `updater-worker.purge_hosts` (lines 484-516) passes each stale host to `purge_host_data` / `purge_similarity_for_host`, which re-normalise it through `normalize_host` before `DELETE ... WHERE host = ?`.\n- Serving-time filtering (`_row_host`).\n\n**Regression risk: low, but there is an interaction to record.** Join hosts now use the crawler's spelling (`[::1]`, `xn--...`). `normalize_host` returns IPv6 without brackets and does no punycode conversion. A stale `[::1]` would therefore be purged as `::1` and match no rows, and a denylist entry typed as a unicode IDN never matches the punycode join host. Both are pre-existing and accepted as known limitations. The two functions now sit side by side with different contracts; the new docstring is what stops a later reader from merging them.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"module-level import `from data.moderation import ensure_moderation_schema, list_active_denied_hosts` (line 26)\">\n**What changes.** `normalize_host_token` is added to this single-line import.\n\n**What depends on it.** The whole module. The import sits after the `sys.path` setup (lines 16-22), which puts `engine/server` and `engine/server/api` at `sys.path[0]`.\n\n**Regression risk: low.** A misspelt name raises ImportError at load, which the new test's importlib load and any run of the job both catch.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"fetch_hosts() (lines 219-250), the line `host_value = str(host).strip().lower()` (243)\">\n**What changes.** Line 243 becomes `host_value = normalize_host_token(str(host))`. The `if host_value:` guard on line 244 already skips None. Everything else stays the same:\n- the User-Agent `peertube-graph-whitelist-sync/1.0`\n- `(HTTPError, URLError)` \u2192 RuntimeError\n- the payload shapes (a dict with `\"data\"`, or a list; `entry.get(\"host\")` for dicts)\n- `ValueError(\"Unexpected whitelist JSON shape.\")`\n- `ValueError(\"Whitelist contained no hosts.\")` when no entry survives\n\n**What depends on it.**\n- `main()` line 571 feeds `remote_hosts` into the rest of the job:\n  - include mode: `selected_hosts_before_deny = remote_hosts` (609)\n  - exclude mode: `source_hosts - remote_hosts` (607), where `source_hosts` comes from `source.videos.instance_domain` and is therefore crawler-normalised\n  - `- denylisted_hosts` (610-612)\n  - `sync_hosts` (640)\n  - `rebuild_content_tables` (641), which copies channels, videos and embeddings `WHERE instance_domain IN (hosts)`\n- The new test calls it directly with a `file://` URL. `urlopen` accepts a `Request` for `file:`, and the timeout has no effect there.\n\n**Regression risk: medium in behaviour, low in code.**\n- Entries that used to keep a non-crawler spelling now match the crawl DB. In include mode `rebuild_content_tables` may copy more rows for them; in exclude mode fewer hosts show up as falsely \"missing\".\n- `sync_hosts` (lines 420-445) deletes every `instances.host` row not in the new set. On the first run, old-spelling rows in `whitelist.db` are therefore replaced wholesale.\n- If every entry normalises to None, the job still raises \"Whitelist contained no hosts.\", as the requirements require.\n- `str(host)` on a truthy non-string entry (dict or bool) differs from the crawler's `extractWhitelistHost` (`crawler.ts:290-304`, which accepts only strings and numbers). This predates the build and is out of scope.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"module top level: sys.path mutation (16-22), imports of scripts.cli_format and server_config (24-25), INSTANCE_/CHANNEL_/VIDEO_COLUMNS parsed from engine/crawler/schema.sql at import (36, 92-96), __main__ guard (676)\">\n**What changes.** Nothing. This matters only because the new test loads the file through `importlib.util.spec_from_file_location`. The filename is hyphenated, so the spec needs an identifier-like module name.\n\n**What depends on it.**\n- The load works only if `engine/crawler/schema.sql` has the `instances`, `channels` and `videos` `CREATE TABLE IF NOT EXISTS` blocks.\n- It also needs `engine/server/scripts/cli_format.py` and `engine/server/api/server_config.py`.\n- `main()` runs only under `if __name__ == \"__main__\"` (line 676), so loading starts no job.\n\n**Regression risk: low.**\n- Loading leaves `engine/server` and `engine/server/api` on `sys.path` for the rest of the pytest session.\n- `engine/server/api/server.py` has the same module name, `server`, as `client/backend/server.py`, which `tests/active/conftest.py` imports first. `sys.modules` keeps the Client module, so later imports stay safe, but only because of that ordering.\n- If `schema.sql` moves, the test errors at import. That is a loud failure.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"sync_hosts() (lines 420-445) and ensure_whitelist_schema() (253-267), used by the new test\">\n**What changes.** Nothing.\n\n**What depends on it.** The new acceptance test stores the fetched set through `ensure_whitelist_schema` and `sync_hosts` into a temporary SQLite file.\n\n**Regression risk: low.** `sync_hosts` is annotated `tuple[int, int]` but returns a 3-tuple `(total, removed, added)` (line 445). The test must not unpack it as a pair. It also needs a plain connection, since there is no `row_factory` requirement here. It must never open the shared `engine/server/db/whitelist.db`.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"module-level parenthesised import `from data.moderation import (...)` (lines 27-32)\">\n**What changes.** `normalize_host_token,` is added in alphabetical position, between `list_active_denied_hosts` and `purge_host_data`, since the existing list is sorted.\n\n**What depends on it.** The whole module.\n\n**Regression risk: low.** An import error would show up at the new test's importlib load.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"fetch_join_hosts() (lines 414-441), the line `value = str(host).strip().lower()` (438)\">\n**What changes.** Line 438 becomes `value = normalize_host_token(str(host))`. The `if value:` guard on line 439 skips None. Everything else stays the same:\n- the User-Agent `peertube-browser-updater/1.0`\n- the RuntimeError `Failed to fetch hosts from ...`\n- the payload shapes\n- `ValueError(\"Unexpected whitelist JSON shape.\")`\n- unlike `fetch_hosts`, it still does not raise on an empty set (an existing asymmetry, kept)\n\n**What depends on it.** `main()` lines 829-872, under `--sync-join-whitelist`:\n- `effective_join_hosts = join_hosts - denied_hosts` (831)\n- `sync_stale_hosts = prod_hosts - effective_join_hosts` (833)\n- `sync_new_hosts = effective_join_hosts - prod_hosts` (834)\n- the stale hosts go to `purge_hosts(...)`: a dry-run plan first, then real deletes from the prod and similarity DBs when `--yes` is passed (843-872)\n- `sync_new_hosts` is written by `write_hosts_file` (line 893) and handed to the crawler as `--whitelist-file` (915), where `loadHostsFromFile` re-normalises it (see the host-filters read-back entry)\n- the orchestrator smoke test drives this function end-to-end, and the new test calls it directly with a `file://` URL\n\n**Correction to the earlier inventory.** The earlier entry said the Python output is always a fixed point of `normalizeHostToken`. That is false. Plain hosts, `[::1]` and `xn--...` do pass through branch 4 unchanged. But a branch-2/3 result with a leading or trailing dot (`https://tube.example./` \u2192 `tube.example.`, matching WHATWG and the crawler's URL mode) is stripped to `tube.example` when the crawler reads the hosts file back.\n\n**Regression risk: medium-high, because this set feeds a destructive purge.**\n- Suppose the port returns None or a different spelling for an entry the crawler normalises to host H. Then H, already in prod, lands in `sync_stale_hosts`, and with `--yes` its instances, channels, videos, embeddings and similarity rows are deleted.\n- Before this change, that already happened for any entry with a scheme, a path or trailing dots. After it, only parity gaps can cause it: IDNA 2003 vs UTS #46, a `.port` ValueError on input WHATWG accepts, or a `urlsplit` difference between Python versions. The net effect should be fewer false stale hosts, but a bug in the helper is a data-loss path, not a cosmetic mismatch.\n- On the first run after the change, prod rows stored under an old non-crawler spelling become stale and are purged. This is accepted; it needs `--yes`, and `--dry-run` shows the plan.\n- The dotted-URL churn described in the read-back entry predates this build and is not a regression.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"write_hosts_file() (lines 465-481) and its two callers (888 exclude file, 893 whitelist file \u2192 --whitelist-file at 915)\">\n**What changes.** Nothing in the code. What it writes changes: `sync_new_hosts` now holds `normalize_host_token` output, one host per line, sorted, UTF-8.\n\n**What depends on it.** The crawler's `instances-cli --whitelist-file` \u2192 `crawler.ts:24-25` \u2192 `loadHostsFromFile`, which trims each line, skips blanks and `#` lines, and runs `normalizeHostToken` again.\n\n**Regression risk: low.** For almost every value the second normalisation changes nothing. The one exception is a URL-form entry whose host has a leading or trailing dot, which becomes a different string in prod than in the join set (see the read-back entry). A host starting with `#` would be dropped as a comment. That can only come from branch 4, which keeps `#`, it predates this build, and it is accepted.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"list_prod_hosts() (lines 444-451) and load_denied_hosts() (454-462), unchanged\">\n**What changes.** Nothing. `list_prod_hosts` keeps `str(row[0]).strip().lower()` by explicit decision.\n\n**What depends on it.** It is the other side of the stale/new set differences in `main()` (lines 831-834).\n\n**Regression risk: low.**\n- Prod `instances.host` rows are written by the crawler, so strip/lower is the identity on normal rows. A row written earlier by Python with dots or a scheme would show up as stale; that falls under the \"existing rows not rewritten\" limitation.\n- The denied hosts come from `list_active_denied_hosts` (rows stored via `normalize_host`), so IDN and IPv6 denylist entries may not match the new spelling. This is accepted.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"module top level (lines 1-33) and __main__ guard (1161)\">\n**What changes.** Nothing beyond the import.\n\n**What depends on it.** The new test's importlib load. The top level only:\n- mutates `sys.path` (adding `engine/server`)\n- imports stdlib modules, `scripts.cli_format` and `data.moderation`\n\n`server_config` is imported lazily inside `parse_args` (lines 85-89), and `resolve_default_engine_service_name`, which runs bash, is only reached from `parse_args`/`main`.\n\n**Regression risk: low.** A correction to the plan: this module does NOT parse `schema.sql` at import (it does so only inside `main`, line 788). Only `sync-whitelist.py` does.\n</impact>\n<impact path=\"engine/crawler/src/host-filters.ts\" element=\"normalizeHostToken() (lines 83-100), the reference implementation, unchanged\">\n**What changes.** Nothing. Changing crawler behaviour is out of scope.\n\n**What depends on it.**\n- `crawler.ts:8, 258, 353`: `fetchWhitelistHosts` \u2192 `parseHostString` \u2192 `normalizeHostToken`.\n- `loadHostsFromFile` (see the next entry).\n- The new fixture pins its output. If this function is edited without rebuilding `dist`, or edited so that a fixture result changes, the new test fails.\n\n**Regression risk: none from this build.** It is the oracle. Its docstring, \"Handle normalize host token.\", is not touched.\n</impact>\n<impact path=\"engine/crawler/src/host-filters.ts\" element=\"loadHostsFromFile() (lines 10-22): re-normalisation of the updater's --whitelist-file (the read-back)\">\n**What changes.** Nothing in the file. This entry records a behaviour the earlier inventory got wrong.\n\n**What depends on it.** `crawler.ts:25` (whitelist file) and `crawler.ts:27` (exclude file). It is also used as the exclude-hosts reader by `channels-worker.ts:74, 108`, `videos-worker.ts:150, 209, 234` and `channels-videos-count-worker.ts:44`.\n\n**The read-back is not always an identity.** Each line goes through `normalizeHostToken`, and a bare host takes branch 4, which strips leading and trailing dots (line 96). The updater writes `normalize_host_token` output, which for URL-form entries is a WHATWG hostname that may end in a dot. Worked through:\n- JoinPeerTube entry `https://tube.example./` \u2192 Python and the crawler's URL mode give `tube.example.`\n- the file-mode crawl stores `tube.example`\n- the next `--sync-join-whitelist` run finds prod `tube.example` missing from the join set \u2192 it is marked stale (purged with `--yes`) and recrawled\n\nPython and the crawler still agree on the value, which is the requirement. The churn existed before this change under a different spelling (the old strip/lower kept `https://tube.example./` as-is), so it is not a regression. None of the 14 pinned inputs is affected.\n\n**Regression risk: low.** Fixing it means making the crawler's file mode and URL mode agree. That is a crawler change and out of scope; it is recorded for the roadmap.\n</impact>\n<impact path=\"engine/crawler/dist/host-filters.js\" element=\"compiled normalizeHostToken (lines 81-99), run by the new test through node\">\n**What changes.** Nothing is written. The new test imports it with `node --input-type=module` via a `file://` URL.\n\n**Checked:**\n- Its only import is `node:fs` (line 4), so no `node_modules` is needed.\n- The body matches `src/host-filters.ts:83-100` line for line.\n- No ignore rule excludes it: the root `.gitignore` ignores `node_modules/` and `engine/.gitignore` ignores only `.pixi/*`.\n\n**What depends on it.** The Node half of the parity test. `engine/crawler/test-url-safety.mjs:7` already imports `./dist/host-filters.js` directly, which is the precedent.\n\n**Regression risk: medium, for the suite rather than production.**\n- The \"dist is stale\" rule decides whether a clean tree goes red. An mtime-only rule can false-fail after a checkout.\n- The git-based rule needs `git` on PATH. This is a linked worktree, where `.git` is a file; `git log -1 --format=%ct -- <path>` still works there.\n- Failure modes such as git missing, a shallow clone, or untracked files must fail loudly, never skip.\n- The build checkpoint must settle the rule.\n</impact>\n<impact path=\"engine/crawler/package.json\" element=\"`&quot;type&quot;: &quot;module&quot;` (line 4) and the build script (line 8: `node node_modules/typescript/bin/tsc -p tsconfig.json`)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- `\"type\": \"module\"` is why `dist/*.js` loads as ESM.\n- The fail-loud message should name the fix: `cd engine/crawler && npm install && npm run build`.\n\n**Regression risk: low.** A build-first variant would need `node_modules/typescript`, which a fresh worktree lacks. That supports fail-loudly.\n</impact>\n<impact path=\"engine/crawler/src/crawler.ts\" element=\"crawl() whitelist source (lines 23-36), fetchWhitelistHosts() (246-269), extractWhitelistEntries() (274-285), extractWhitelistHost() (290-304), parseHost() (334-347), parseHostString() (352-354)\">\n**What changes.** Nothing. This is the crawler's own reader of the same payload, the behaviour the Python readers must match.\n\n**What depends on it.** `instances-cli`, which the updater runs with `--whitelist-file` (or `--whitelist-url`).\n\n**Regression risk: none from this build.** Differences outside the port stay as they are:\n- The crawler accepts only string or number hosts and trims before normalising; Python calls `str(host)` on any truthy value.\n- The crawler raises `Unexpected whitelist JSON shape.` for a dict whose `data` is not an array; Python accepts `\"data\" in payload` whatever its type.\n- `parseHost` returns `ref.host.toLowerCase()` without normalising (line 340).\n</impact>\n<impact path=\"engine/server/db/jobs/compare-join-hosts.py\" element=\"hosts_from_payload() (line 80) and load_local_hosts() (line 96), both `str(...).strip().lower()`\">\n**What changes.** Nothing. Explicitly out of scope.\n\n**What depends on it.** The operator diagnostic that compares JoinPeerTube hosts with the local `instances` table.\n\n**Regression risk: low, but it drifts.** After this build it is the only Python reader of the list that still uses strip/lower. It can report hosts as \"missing\" (`https://x/` vs `x`) that the jobs now treat as present. This is a roadmap follow-up.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"load_hosts_from_json() (lines ~347-382, own strip/lower at 375), start_whitelist_server() (~396-408), run_orchestrator() (411-450), payload build (964-985)\">\n**What changes.** Nothing in the file. It must still pass.\n\n**Correction to the plan.** The smoke test does NOT go through `fetch_hosts`. It writes `whitelist.json` (`{\"total\", \"data\": [{\"host\": ...}]}`), serves it with `python -m http.server`, and runs `updater-worker.py --whitelist-url` (lines 419-441). That exercises `fetch_join_hosts`.\n\nThe hosts come from `engine/server/db/jobs/tests/test-instances.json` (per `ORCHESTRATOR_SMOKE_TEST.md:42`) or from prod rows, which are plain crawler-normalised hosts that pass through the helper unchanged. Its expectations therefore hold.\n\n**Regression risk: low for correctness.** Running it needs node, a built `dist`, the embedding stack and network access. That limits whether it can be run here, but it is not a regression.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-moderation-integration.py\" element=\"standalone script importing data.moderation (lines 31-38)\">\n**What changes.** Nothing. It must still pass.\n\n**What depends on it.** It imports `ensure_moderation_schema`, `list_active_denied_hosts`, `normalize_host`, `now_ms`, `purge_host_data` and `purge_similarity_for_host`, plus `data.serving_moderation`. It does not import either job. Its own strip/lower calls (lines 484, 947, 1030) are local set arithmetic.\n\n**Regression risk: low.** It can break only if the `moderation.py` edit fails to import or alters `normalize_host`. It is run separately from `validate_tests.py`.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"startup import `from data.moderation import ensure_moderation_schema` (line 97)\">\n**What changes.** Nothing in the file. The module it imports gains a function and an `ipaddress` import.\n\n**What depends on it.** The Engine process, and so every Engine-backed test through the `engine` fixture in `conftest.py`.\n\n**Regression risk: very low.** Only an import-time failure of `moderation.py` matters, and it would stop the Engine from starting.\n</impact>\n<impact path=\"engine/server/data/serving_moderation.py\" element=\"`from data.moderation import ModerationFilterStats, filter_rows_by_moderation` (line 11)\">\n**What changes.** Nothing.\n\n**What depends on it.** Serving-time moderation in the Engine and in the integration script.\n\n**Regression risk: very low.** It is affected only by an import-time failure of `moderation.py`.\n</impact>\n<impact path=\"engine/server/db/jobs/instance-denylist-cli.py\" element=\"normalize_host usage (import at line 21, call at 145)\">\n**What changes.** Nothing. Out of scope.\n\n**What depends on it.** The operator's denylist entries, which feed `list_active_denied_hosts`. Both jobs subtract that set from the normalised join set.\n\n**Regression risk: low.** IDN and IPv6 entries are stored in unicode or without brackets, so they may not match the new crawler-style spelling. This predates the build and is accepted.\n</impact>\n<impact path=\"engine/server/db/jobs/channel-moderation-cli.py\" element=\"normalize_host usage (import at line 23, call at 78)\">\n**What changes.** Nothing. Out of scope.\n\n**What depends on it.** `channel_moderation.instance_domain` rows, which serving-time filtering compares with `normalize_host(row host)`.\n\n**Regression risk: none from this build.** It never reads the output of `normalize_host_token`.\n</impact>\n<impact path=\"engine/crawler/schema.sql\" element=\"instances/channels/videos CREATE TABLE blocks, parsed at import by sync-whitelist.py\">\n**What changes.** Nothing.\n\n**What depends on it.** `sync-whitelist.py` (lines 36 and 92-96) parses these blocks at import, so the new test's importlib load depends on this file.\n\n**Regression risk: low.** If it moves or changes, the test errors loudly.\n</impact>\n<impact path=\"tests/active/test_host_normalisation.py\" element=\"new pytest file (working name)\">\n**What changes.** A new file.\n- It puts `engine/server` on `sys.path` the way `test_db.py:22-26` and `test_random_videos.py:19-24` do (a `SERVER_DIR` constant, `sys.path.insert(0, ...)`, `# noqa: E402` imports), then imports `normalize_host_token` from `data.moderation`.\n- **Part 1:** a test parametrised over the fixture pairs.\n- **Part 2:** one `node --input-type=module` subprocess.\n  - Before it runs, `pytest.fail` with a message naming the fix if `shutil.which(\"node\")` finds nothing, if `dist/host-filters.js` is missing, or if `dist` is stale.\n  - The inline script reads the fixture inputs as JSON on stdin and imports the `dist` module by `file://` URL.\n  - The existing precedents (`test_frontend_*.py`) call `\"node\"` without a which-check.\n- **Part 3:** the job tests.\n  - Load both jobs with `importlib.util.spec_from_file_location` (precedent: `test_similar.py:36-41`).\n  - Serve a `file://` payload from `tmp_path`.\n  - `fetch_hosts` returns `{\"tube.example\"}`, which is then stored through `ensure_whitelist_schema` + `sync_hosts` into a temp DB (3-tuple return).\n  - A mixed-invalid, dict-shape payload asserts `fetch_join_hosts == fetch_hosts`.\n\n**What depends on it.** `validate_tests.groups()` picks it up automatically (`tests/active/test_*.py`). It is unmapped until harvest, so it runs on every invocation. It uses no Engine fixture, but pytest still imports `conftest.py`, which imports the Client backend.\n\n**Regression risk: low for production, medium for suite stability.**\n- The node and staleness gates are the likely source of false reds.\n- The module docstring should follow the suite's style: a summary line, then bullets for each claim, as in `test_similar.py:1-18` and `test_db.py:1-8`.\n- It must never touch `engine/server/db/whitelist.db`, which is shared across worktrees.\n- It must not request the `engine`, `engine_client`, `unpublished_client` or `dataset` fixtures.\n</impact>\n<impact path=\"tests/active/host_tokens.json\" element=\"new JSON fixture of {input, expected} pairs (14 pinned values, null for None)\">\n**What changes.** A new file holding the pinned pairs. It includes `\"https://b\u00fccher.example/\"`, so it must be read with `encoding=\"utf-8\"`, and the node subprocess needs `text=True, encoding=\"utf-8\"`. Otherwise a non-UTF-8 locale corrupts the `\u00fc`.\n\nOptional extra pair from step 4: `\"https://tube.example./\"` \u2192 `\"tube.example.\"`. It pins the dot-keeping URL behaviour on both sides. WHATWG, `urlparse` and the crawler all agree on it, so it adds no failure mode. Leave it out if the set must stay at exactly the 14 required values.\n\n**What depends on it.** Both halves of the parity test.\n\n**Regression risk: low.** It is not a `test_*.py` file, so it is not a group. At harvest the `test_groups` entry must list it, or an edit to the fixture alone will not re-run the test.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"module-level imports (lines 29-41: client/backend inserted at sys.path[0], `import server`, `lib.*`); Engine fixtures\">\n**What changes.** Nothing.\n\n**What depends on it.** Every test in `tests/active`, including the new one.\n\n**Regression risk: low.** The job loads put `engine/server/api` (which holds `server.py`, `http_utils.py`, `server_config.py`) on `sys.path`. By then conftest has already cached the Client's `server` and `lib` in `sys.modules`. `client/backend` holds only `server.py` and `lib/`, so `data`, `scripts` and `server_config` resolve to the Engine copies. The new test leaves `sys.path` mutated, the same as existing tests do.\n</impact>\n<impact path=\"tests/active/test_frontend_videos.py\" element=\"node invocation precedent (line 66); also test_frontend_blocks.py:79, test_frontend_profile.py:70, test_frontend_reactions.py:134/145\">\n**What changes.** Nothing.\n\n**What depends on it.** These tests already need `node` on the PATH that pytest sees, so the suite already goes red without node. The new hard dependency is consistent with that.\n\n**Regression risk: none.** Listed so the new test's node call and its message follow the existing convention.\n</impact>\n<impact path=\"engine/crawler/test-url-safety.mjs\" element=\"standalone node harness importing ./dist/host-filters.js (line 7)\">\n**What changes.** Nothing.\n\n**What depends on it.** Nothing automated: it is run by hand, as is `test-text-limits.mjs`.\n\n**Regression risk: none.** It shows that `dist/host-filters.js` loads under plain node with no `node_modules`.\n</impact>\n<impact path=\".un/skills/devsecops/scripts/validate_tests.py\" element=\"groups() (584-613), claimed()/digest (616-677), runner() (498-518)\">\n**What changes.** Nothing.\n\n**What depends on it.** The suite run that must stay green:\n- `groups()` discovers the new `test_*.py`, and an unmapped group always runs.\n- `claimed()` digests only the test file plus its mapped files, so the fixture is covered only once it is mapped.\n- `runner()` uses `pixi run --manifest-path` only if `pixi.toml` or `pixienv/pixi.toml` exists. Neither exists in this worktree (checked the root and `engine/`), so it uses `sys.executable`.\n\n**Regression risk: low.** The Python version that proves parity depends on this runner and may differ from the job runtime.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups map (lines 14-88)\">\n**What changes.** Nothing in this worktree. The entry is added at harvest on main. It should map `test_host_normalisation.py` to:\n- `engine/server/data/moderation.py`\n- `engine/server/db/jobs/sync-whitelist.py`\n- `engine/server/db/jobs/updater-worker.py`\n- `engine/crawler/src/host-filters.ts`\n- `engine/crawler/dist/host-filters.js`\n- `tests/active/host_tokens.json`\n\n**What depends on it.** Stale-group selection.\n\n**Regression risk: low.** An entry that lists too few files misses re-runs. Also, `.un/` is in the root `.gitignore`, so this config is local and not versioned.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked suite record\">\n**What changes.** It is rewritten by the post-build `validate_tests.py` run.\n\n**What depends on it.** The comparison against the baseline (green: code 0, variant false).\n\n**Regression risk: none functionally.** It will conflict on merge: take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n</impact>\n<impact path=\"tests/last_test_output.txt\" element=\"tracked captured pytest output\">\n**What changes.** It is rewritten by the post-build run.\n\n**What depends on it.** Nothing in code.\n\n**Regression risk: none.** Resolve its merge conflict the same way as `last_test_validation.json`.\n</impact>\n",
  "docs_checklist": "- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md step 2 \"Notes:\" now has a bullet on how `sync-whitelist.py` turns whitelist entries into hosts through `normalize_host_token`.\n- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: UPDATER_WORKER.md now explains how `--sync-join-whitelist` normalises hosts, when it purges stale hosts, and the `--yes`/`--dry-run` flags that control that.\n- [x] `docs/project/issues/06-normalise-instance-hosts.md` - updated: Issue 06 is marked delivered: status is `bug, complete`, five of the six acceptance criteria are ticked, and a delivery comment is added. The file has not been moved to `archive/` yet because I have no tool that can move or delete files.\n- [x] `docs/project/plans/10-normalise-instance-hosts.md` - updated: I marked plan 10 as delivered, pointed it at build plan 16, and added a \"Delivery\" section recording what the build settled and three corrections to the plan's reading of the code. I did not move the file to `plans/archive/`, because I have no tool that can move files.\n- [x] `docs/project/roadmap.md` - updated: Roadmap: issue 06 moved to Delivered, dropped from the open-security lists, and three host-normalisation follow-ups added under M6.\n- [x] `DEPLOYMENT.md` - out of scope: It mentions `sync-whitelist.py` only in the run-order warning on line 43: run it after `crawl:videos` completes. It says nothing about how hosts-list entries are parsed or normalised, and that ordering is unchanged.\n- [x] `README.md` - out of scope: Line 14 says only that filtering keeps instances that appear in the JoinPeerTube whitelist. That is still true, and the README makes no claim about entry spelling.\n- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - out of scope: It describes the smoke test's inputs (`test-instances.json` or prod rows) and flow, and makes no claim about host normalisation or which fetch function is used. Its plain lowercase hosts pass through `normalize_host_token` unchanged, so nothing it says has become false.\n- [x] `docs/project/security-audit/run-2/REPORT.md` - out of scope: This is a point-in-time audit record, not living documentation. Its line saying the moderation layer normalises hosts through `normalize_host` before comparing or deleting is still true: purges and serving filters still use `normalize_host`. The finding SI4-M1 is closed through the issue file, not by editing the report.\n- [x] `docs/project/adr/0001-derived-interaction-event-ids.md` - out of scope: It covers interaction event ids. It does not touch host normalisation or the whitelist jobs. The same holds for ADRs 0002 (trusted proxy client address), 0003 (metadata endpoint uuid entries), 0004 (CORS) and 0005 (raw event retention). None of them makes a claim about JoinPeerTube host parsing.",
  "docs": [
    {
      "path": "DATA_BUILD.md",
      "note": "Section \"2) Filter to JoinPeerTube whitelist\", Notes (lines 145-149): add one bullet. It should say that each whitelist entry is normalised the way the crawler normalises hosts (`data.moderation.normalize_host_token`, a port of `normalizeHostToken`):\n- URL-like entries lose the scheme, userinfo, port and path.\n- Bare entries lose leading and trailing dots.\n- Entries that normalise to nothing are skipped."
    },
    {
      "path": "engine/server/db/jobs/docs/UPDATER_WORKER.md",
      "note": "\"What Exactly Is Collected\" (line 59, \"Instances: from whitelist source\"): state that with `--sync-join-whitelist` the fetched hosts are normalised by the same crawler-equivalent rule before the new/stale/denylist comparison. State the one-time effect: rows stored under an older spelling show up as stale on the first run, so review them with `--dry-run` before `--yes`. The \"Important Flags\" list (lines 101-115) could also gain `--sync-join-whitelist`, `--yes` and `--dry-run`, which it currently omits."
    },
    {
      "path": "docs/project/issues/06-normalise-instance-hosts.md",
      "note": "At harvest:\n- Tick the acceptance criteria.\n- Set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.\n- Record the accepted limitations: branch 4 keeps `@ ? #` and ports; parity is proven only for fixture inputs; `compare-join-hosts.py` still uses strip/lower; the file-mode read-back strips dots from URL-form hosts that end in a dot."
    },
    {
      "path": "docs/project/plans/10-normalise-instance-hosts.md",
      "note": "At harvest: mark it delivered and point to `16-10-normalise-instance-hosts.md`. Note the corrections found in discovery:\n- The orchestrator smoke test exercises `fetch_join_hosts`, not `fetch_hosts`.\n- Only `sync-whitelist.py` parses `schema.sql` at import.\n- The updater's hosts file is not always left unchanged when the crawler reads it back (dotted URL-form hosts)."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "Follow-up entries, all out of scope for this build:\n- Move `compare-join-hosts.py` (`hosts_from_payload`, line 80) onto `normalize_host_token`.\n- Make the crawler's `--whitelist-file` mode (`loadHostsFromFile`, branch 4 strips dots) and its URL mode (keeps the WHATWG trailing dot) agree, so dotted entries stop churning through purge and recrawl.\n- Optionally, align `normalize_host` (denylist input) on bracketed IPv6 and punycode."
    }
  ],
  "reassessments": 2,
  "draft": "## Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/moderation.py` | adds `import ipaddress`, the constant `URL_SCHEME_PREFIXES`, `normalize_host_token()` and the private `_whatwg_hostname()` directly after `normalize_host`; the header bullet names both normalisers |\n| `engine/server/db/jobs/sync-whitelist.py` | line 26 import gains `normalize_host_token`; `fetch_hosts` line 243 swapped |\n| `engine/server/db/jobs/updater-worker.py` | the parenthesised import gains `normalize_host_token,` between `list_active_denied_hosts` and `purge_host_data`; `fetch_join_hosts` line 438 swapped |\n| `tests/active/host_tokens.json` | new, 15 `{input, expected}` pairs |\n| `tests/active/test_host_normalisation.py` | new, 5 tests: Python table, Node table, three job tests |\n| `DATA_BUILD.md`, `engine/server/db/jobs/docs/UPDATER_WORKER.md` | one note each (text below) |\n\nNo new file under `engine/`, no dependency, no new interface. The issue, plan and roadmap doc edits happen at harvest, as settled.\n\n## What the build needs to test\n\n1. `normalize_host_token` returns the pinned value for every fixture input. That covers all four branches, userinfo, port, IPv6 brackets, punycode, and the None cases.\n2. The crawler's compiled `normalizeHostToken` returns the same pinned values, so Python == crawler on the fixture.\n3. The test fails loudly when `node` is missing, `dist/host-filters.js` is missing, or `dist` is stale.\n4. `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` into `{\"tube.example\"}`, and `sync_hosts` stores that one row in a temporary DB.\n5. Entries that normalise to None are dropped, the fetch completes, and `fetch_join_hosts` == `fetch_hosts` on a dict-shape payload.\n6. `fetch_hosts` still raises `Whitelist contained no hosts.` when every entry normalises to None. This is existing behaviour the requirements restate, and it costs one assert.\n\n`test-moderation-integration.py`, `test-orchestrator-smoke.py` and `validate_tests.py` are run, not changed.\n\n## `engine/server/data/moderation.py`\n\nHeader comment, line 9:\n\n```python\n# - host normalization (normalize_host for operator input, normalize_host_token for hosts-list entries, a port of the crawler's normalizeHostToken),\n```\n\nImports, alphabetical in the existing block:\n\n```python\nimport ipaddress\nimport re\nimport sqlite3\nfrom dataclasses import dataclass\nfrom datetime import datetime, timezone\nfrom urllib.parse import urlparse\n```\n\nModule constant, placed after the imports and before `ModerationFilterStats`:\n\n```python\nURL_SCHEME_PREFIXES = (\"http://\", \"https://\")\n```\n\nNew code directly after `normalize_host`:\n\n```python\ndef normalize_host_token(value: str) -> str | None:\n    \"\"\"Normalize a hosts-list entry exactly as the crawler's normalizeHostToken (engine/crawler/src/host-filters.ts) does; unlike normalize_host, bare entries keep ports and URL entries yield the WHATWG hostname.\"\"\"\n    raw = value.strip().lower()\n    if not raw:\n        return None\n    try:\n        if raw.startswith(URL_SCHEME_PREFIXES):\n            return _whatwg_hostname(raw)\n        if \"/\" in raw:\n            return _whatwg_hostname(f\"https://{raw}\")\n        return raw.strip(\".\") or None\n    except ValueError:\n        return None\n\n\ndef _whatwg_hostname(url: str) -> str | None:\n    \"\"\"Handle the hostname WHATWG URL.hostname returns for url; raise ValueError where WHATWG throws.\"\"\"\n    parsed = urlparse(url)\n    # Reading .port raises ValueError on a non-numeric or out-of-range port, which WHATWG also rejects.\n    _ = parsed.port\n    host = parsed.hostname or \"\"\n    if not host:\n        return None\n    if \":\" in host:\n        return f\"[{ipaddress.IPv6Address(host).compressed}]\"\n    if not host.isascii():\n        host = host.encode(\"idna\").decode(\"ascii\")\n    return host.lower() or None\n```\n\nInvariants and decisions:\n- **Order.** The branch order and tests match `host-filters.ts:83-100` exactly. `raw.strip(\".\")` is `replace(/^\\.+|\\.+$/g, \"\")`. Branch 4 never parses, so `tube.example:9000`, `@`, `?`, `#` and non-ASCII characters pass through unchanged.\n- **One except.** A single `except ValueError` stands in for the crawler's whole-body try/catch. It also catches `UnicodeError` (idna), `ipaddress.AddressValueError`, urlsplit's `Invalid IPv6 URL`, and the `.port` error, because all of them subclass ValueError.\n- **IPv6.** It is detected by `\":\" in host`. `.hostname` never carries the port, so a colon can only come from an IPv6 literal. `.compressed` is the form WHATWG serialises, and the brackets are put back.\n- **IDNA only for non-ASCII.** Only non-ASCII hosts go through the `idna` codec. ASCII hosts skip it, so `a..b` and labels over 63 characters are kept, as WHATWG keeps them.\n- **Dots kept.** A trailing or leading dot in a URL-form host is kept (`https://tube.example./` \u2192 `tube.example.`), exactly as WHATWG keeps it. The fixture pins this.\n- **Nothing at import.** There is no module-level work beyond the tuple constant, because the Engine imports this module at startup.\n- **`normalize_host` untouched.**\n\n## Job call sites\n\n`sync-whitelist.py` line 26:\n\n```python\nfrom data.moderation import ensure_moderation_schema, list_active_denied_hosts, normalize_host_token\n```\n\n`fetch_hosts`, line 243 only:\n\n```python\n        host_value = normalize_host_token(str(host))\n```\n\n`updater-worker.py` import:\n\n```python\nfrom data.moderation import (\n    ensure_moderation_schema,\n    list_active_denied_hosts,\n    normalize_host_token,\n    purge_host_data,\n    purge_similarity_for_host,\n)\n```\n\n`fetch_join_hosts`, line 438 only:\n\n```python\n        value = normalize_host_token(str(host))\n```\n\nThe existing `if host_value:` / `if value:` guards already skip None. The User-Agents, error types and messages, payload-shape handling, the empty-set raise in `fetch_hosts` and the missing one in `fetch_join_hosts` are all unchanged. `list_prod_hosts` is untouched.\n\n## `tests/active/host_tokens.json`\n\n```json\n[\n  {\"input\": \" Tube.Example \", \"expected\": \"tube.example\"},\n  {\"input\": \"tube.example.\", \"expected\": \"tube.example\"},\n  {\"input\": \"..tube.example..\", \"expected\": \"tube.example\"},\n  {\"input\": \"https://Tube.Example/\", \"expected\": \"tube.example\"},\n  {\"input\": \"http://tube.example:8080/path\", \"expected\": \"tube.example\"},\n  {\"input\": \"https://user@tube.example\", \"expected\": \"tube.example\"},\n  {\"input\": \"tube.example/videos\", \"expected\": \"tube.example\"},\n  {\"input\": \"tube.example:9000\", \"expected\": \"tube.example:9000\"},\n  {\"input\": \"https://[::1]:8080/\", \"expected\": \"[::1]\"},\n  {\"input\": \"https://b\u00fccher.example/\", \"expected\": \"xn--bcher-kva.example\"},\n  {\"input\": \"\", \"expected\": null},\n  {\"input\": \"   \", \"expected\": null},\n  {\"input\": \".\", \"expected\": null},\n  {\"input\": \"https://\", \"expected\": null},\n  {\"input\": \"https://tube.example./\", \"expected\": \"tube.example.\"}\n]\n```\n\nThe file holds the 14 required pairs plus the optional dot-keeping pair from step 4. WHATWG, `urlparse` and the crawler all agree on that pair, and it guards against a later \"fix\" that strips the dot in the port. It is saved as UTF-8 (`\u00fc` written raw), and all inputs are unique, which the Node assertion relies on.\n\n## `tests/active/test_host_normalisation.py`\n\n```python\n\"\"\"The Engine's port of the crawler's host normalisation, and the two jobs that read the JoinPeerTube hosts list through it.\n\n- `data.moderation.normalize_host_token` returns the pinned value for every pair in `host_tokens.json`.\n- The crawler's compiled `normalizeHostToken` (`engine/crawler/dist/host-filters.js`, run under node) returns the same pinned values, so the Python port and the crawler agree on every fixture input. A missing node, a missing dist or a dist older than `src/host-filters.ts` fails the test, never skips it.\n- The whitelist sync job's host fetch turns `https://Tube.Example/` and `tube.example` into the single host `tube.example`, which `sync_hosts` stores as one row.\n- Entries that normalise to nothing are left out of both jobs' host sets, the fetch still completes, and the updater's join-host fetch returns the same set as the sync job's.\n\"\"\"\nfrom __future__ import annotations\n\nimport importlib.util\nimport json\nimport os\nimport shutil\nimport sqlite3\nimport subprocess\nimport sys\n\nimport pytest\nfrom conftest import ROOT\n\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nif str(SERVER_DIR) not in sys.path:\n    sys.path.insert(0, str(SERVER_DIR))\n\nfrom data.moderation import normalize_host_token  # noqa: E402\n\nJOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"\nCRAWLER_DIR = ROOT / \"engine\" / \"crawler\"\nSRC = CRAWLER_DIR / \"src\" / \"host-filters.ts\"\nDIST = CRAWLER_DIR / \"dist\" / \"host-filters.js\"\nBUILD_HINT = \"cd engine/crawler && npm install && npm run build\"\nFIXTURE = ROOT / \"tests\" / \"active\" / \"host_tokens.json\"\nPAIRS = json.loads(FIXTURE.read_text(encoding=\"utf-8\"))\n# Reads a JSON list of inputs on stdin and prints the crawler's normalizeHostToken of each.\nNODE_SCRIPT = \"\"\"\nimport { readFileSync } from \"node:fs\";\nconst { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);\nconst inputs = JSON.parse(readFileSync(0, \"utf8\"));\nprocess.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));\n\"\"\"\n\n\ndef _load_job(module_name: str, filename: str):\n    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)\n    module = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(module)\n    return module\n\n\n@pytest.fixture(scope=\"module\")\ndef jobs():\n    return _load_job(\"sync_whitelist_job\", \"sync-whitelist.py\"), _load_job(\"updater_worker_job\", \"updater-worker.py\")\n\n\ndef _payload_url(tmp_path, payload) -> str:\n    path = tmp_path / \"hosts.json\"\n    path.write_text(json.dumps(payload), encoding=\"utf-8\")\n    return path.as_uri()\n\n\ndef _commit_time(git: str, path) -> int | None:\n    out = subprocess.run([git, \"log\", \"-1\", \"--format=%ct\", \"--\", str(path)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()\n    return int(out) if out else None\n\n\ndef _dist_staleness() -> str | None:\n    \"\"\"Return why dist/host-filters.js is behind src/host-filters.ts, or None when it is current.\"\"\"\n    git = shutil.which(\"git\")\n    if git is None:\n        return \"git is not on PATH, so the freshness of dist/host-filters.js cannot be checked\"\n    src_dirty = subprocess.run([git, \"status\", \"--porcelain\", \"--\", str(SRC)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()\n    src_time = _commit_time(git, SRC)\n    dist_time = _commit_time(git, DIST)\n    # An uncommitted or untracked source is judged by mtime; committed files by commit time, which a checkout does not reorder.\n    if src_dirty or src_time is None or dist_time is None:\n        if DIST.stat().st_mtime < SRC.stat().st_mtime:\n            return \"dist/host-filters.js is older on disk than the edited src/host-filters.ts\"\n        return None\n    if src_time > dist_time:\n        return \"src/host-filters.ts was committed after dist/host-filters.js was last rebuilt and committed\"\n    return None\n\n\n@pytest.mark.parametrize(\"pair\", PAIRS, ids=[repr(pair[\"input\"]) for pair in PAIRS])\ndef test_python_port_returns_pinned_value(pair):\n    assert normalize_host_token(pair[\"input\"]) == pair[\"expected\"]\n\n\ndef test_crawler_dist_returns_pinned_values():\n    node = shutil.which(\"node\")\n    if node is None:\n        pytest.fail(f\"node is not on PATH; install Node.js, then run: {BUILD_HINT}\")\n    if not DIST.is_file():\n        pytest.fail(f\"{DIST} is missing; run: {BUILD_HINT}\")\n    stale = _dist_staleness()\n    if stale:\n        pytest.fail(f\"{stale}; run: {BUILD_HINT}\")\n    inputs = [pair[\"input\"] for pair in PAIRS]\n    proc = subprocess.run(\n        [node, \"--input-type=module\", \"-e\", NODE_SCRIPT], input=json.dumps(inputs), capture_output=True, text=True, encoding=\"utf-8\", timeout=60,\n        env={**os.environ, \"HOST_FILTERS_URL\": DIST.as_uri()},\n    )\n    assert proc.returncode == 0, proc.stderr\n    assert dict(zip(inputs, json.loads(proc.stdout))) == {pair[\"input\"]: pair[\"expected\"] for pair in PAIRS}\n\n\ndef test_sync_job_stores_one_spelling_per_host(jobs, tmp_path):\n    sync, _ = jobs\n    hosts = sync.fetch_hosts(_payload_url(tmp_path, [\"https://Tube.Example/\", \"tube.example\"]))\n    assert hosts == {\"tube.example\"}\n    conn = sqlite3.connect(tmp_path / \"whitelist.db\")\n    try:\n        sync.ensure_whitelist_schema(conn)\n        # sync_hosts returns (total, removed, added) despite its two-element annotation.\n        counts = sync.sync_hosts(conn, hosts)\n        conn.commit()\n        stored = [row[0] for row in conn.execute(f\"SELECT host FROM {sync.TABLE_NAME}\")]\n    finally:\n        conn.close()\n    assert counts == (1, 0, 1)\n    assert stored == [\"tube.example\"]\n\n\ndef test_jobs_drop_entries_that_normalise_to_nothing(jobs, tmp_path):\n    sync, updater = jobs\n    entries = [\"\", \"   \", \".\", \"https://\", \"https://Tube.Example/\", \"other.example.\"]\n    url = _payload_url(tmp_path, {\"data\": [{\"host\": entry} for entry in entries]})\n    expected = {\"tube.example\", \"other.example\"}\n    assert sync.fetch_hosts(url) == expected\n    assert updater.fetch_join_hosts(url) == expected\n\n\ndef test_sync_job_still_rejects_a_list_with_no_usable_host(jobs, tmp_path):\n    sync, _ = jobs\n    with pytest.raises(ValueError, match=\"Whitelist contained no hosts.\"):\n        sync.fetch_hosts(_payload_url(tmp_path, [\"   \", \".\", \"https://\"]))\n```\n\nSeams and decisions in the test:\n- **Fixture paths.** `ROOT` comes from `conftest`, as `test_similar.py` uses it. `SERVER_DIR` and the `# noqa: E402` import follow `test_db.py:22-26`. The file uses no Engine fixture, so it runs in the normal `validate_tests.py` pass.\n- **Loading the jobs.** Both are loaded through `spec_from_file_location` with identifier-like module names, following `test_similar.py:36-41`. Neither job defines a dataclass, so no `sys.modules` registration is needed. `main()` sits behind `__main__` guards. The module-scoped fixture loads each job once, and `sync-whitelist.py` parses `schema.sql` at that point, so if the file moves the tests error loudly.\n- **Payloads.** They are served as `file://` URIs from `tmp_path`. `urlopen` accepts a `Request` with headers for `file:` and ignores the timeout, so no server thread is needed. The mixed test uses the dict shape and the first test the list shape, so both shapes are covered. `\"\"` is dropped by the jobs' existing `if not host` before the helper runs; `\"   \"`, `\".\"` and `\"https://\"` reach the helper and return None.\n- **Temporary database.** Every database is a `tmp_path` file. The shared `engine/server/db/whitelist.db` is never opened.\n- **Node call.**\n  - It uses the absolute path from `shutil.which`.\n  - The dist URL is passed through the environment, which is `os.environ` plus one key, so PATH and the rest are kept.\n  - `encoding=\"utf-8\"` covers the raw `\u00fc` in stdout under non-UTF-8 locales. stdin is ASCII because `json.dumps` escapes by default.\n  - The zip into a dict makes a pytest failure show exactly which input differs.\n- **Staleness rule (recommended for the build checkpoint).**\n  - Committed files are compared by the last commit time of `src/host-filters.ts` versus `dist/host-filters.js`, which a fresh checkout's write order cannot disturb.\n  - An uncommitted or untracked source, or a path with no history (for example a shallow boundary or untracked `dist`), falls back to mtime.\n  - A missing `git`, or a git command that fails (`check=True` raises `CalledProcessError`), is a loud fail or error, never a skip.\n  - Ceiling: a commit that changes only a comment in `src` without recommitting `dist` reports stale. The fix, rebuild and commit, is cheap, and a false red is preferred to a silent pass.\n  - The alternative the checkpoint may pick instead is build-first. It is rejected because it needs `node_modules/typescript` and would write to the tree during a test run.\n\n## Documentation text\n\n`DATA_BUILD.md`, a new bullet appended to the \"Notes:\" list under section 2:\n\n```markdown\n- Each whitelist entry is normalised the way the crawler normalises hosts (`data.moderation.normalize_host_token`, a port of `normalizeHostToken`): URL-like entries lose the scheme, userinfo, port and path; bare entries lose leading and trailing dots; entries that normalise to nothing are skipped.\n```\n\n`UPDATER_WORKER.md`, line 59 becomes:\n\n```markdown\n- Instances: from whitelist source (JoinPeerTube URL by default). With `--sync-join-whitelist` the fetched hosts are normalised by the crawler-equivalent rule (`data.moderation.normalize_host_token`) before the new/stale/denylist comparison. Prod rows stored under an older spelling show up as stale on the first run after this change, so review the plan with `--dry-run` before passing `--yes`.\n```\n\nUnder \"Important Flags\", add `- \\`--sync-join-whitelist\\`, \\`--yes\\`, \\`--dry-run\\`` after `--whitelist-url`.\n\n## Verification commands (build step)\n\n1. `python -m pytest tests/active/test_host_normalisation.py -q` from the worktree root.\n2. `python engine/server/db/jobs/tests/test-moderation-integration.py`, then `test-orchestrator-smoke.py`. The smoke test drives `fetch_join_hosts` through `--whitelist-url`, not `fetch_hosts`, and needs node, a built `dist`, the embedding stack and network. If any of these is missing, report the run as not possible here rather than green.\n3. `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts`, compared against the green baseline (code 0, variant false).\n\n## Check against plan and requirements (pass 1: converged)\n\n- **Helper.** It lives in `moderation.py` after `normalize_host`, which is unchanged. It is stdlib only, adds one module constant and has a one-line docstring naming the port and the difference from `normalize_host`. All four branches are in order, and branch 4 does no parse and no punycode. Traced by hand, all 15 fixture pairs give the expected value through `urlparse` / `ipaddress` / `idna`.\n- **Jobs.** Only the one expression and the import change in each. `list_prod_hosts`, `compare-join-hosts.py`, the CLIs and the crawler are untouched.\n- **Acceptance criteria.**\n  - The Python table test and the Node test on `dist` share one fixture.\n  - Fail-loudly covers node, a missing dist and a stale dist, without depending on `node_modules`.\n  - The `https://Tube.Example/` + `tube.example` payload gives `{tube.example}`, stored via `sync_hosts` in a temp DB.\n  - None entries are dropped while the fetch completes.\n  - `fetch_join_hosts` == `fetch_hosts`.\n  - The empty-set raise is kept.\n- **Style.** One statement per line, no softwrap, `from __future__ import annotations` in both touched Python modules that already use it, no new dependency, no single-implementation interface.\n- **Deliberate simplifications, each with its ceiling and upgrade path.**\n  - Parity is proven only on the fixture and on the interpreter that runs pytest. The upgrade is to add fixture inputs.\n  - There is no forbidden-host-code-point check. Upgrade: one module constant plus one test in `_whatwg_hostname`, the first time a fixture input exposes the gap.\n  - IPv6 scope ids are accepted and IDNA 2003 is used, as the settled limitations state.\n\nNothing is left unresolved that needs the operator. The staleness rule remains for the build checkpoint to settle, as the requirements say.",
  "coordination": "Phase 2 needs `node` on PATH in the build environment, plus a committed or rebuilt engine/crawler/dist/host-filters.js (present in the tree now). If node is missing, the checkpoint fails by design, and the operator must install Node.js and run `cd engine/crawler && npm install && npm run build`. The phase 3 post-build run of test-orchestrator-smoke.py also needs the embedding stack and network access; if either is missing, it is reported as not run, not as green. No credentials are needed.",
  "tests": {
    "tests/tmp/test_10_normalise_instance_hosts_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_10_normalise_instance_hosts_phase1.py:53 \u2014 for each of the 15 pinned inputs (parametrised, ids repr(input)), `moderation.normalize_host_token(value) == expected`, with None where the pinned value is null",
          "expected": "The pinned value for each input. \"tube.example\" for the 7 trim, dot, scheme, userinfo, port and path inputs. \"tube.example:9000\", \"[::1]\" and \"xn--bcher-kva.example\". \"tube.example.\" for \"https://tube.example./\". None for \"\", \"   \", \".\" and \"https://\". The first 14 are the WHATWG values pinned in the operator-confirmed requirements. The 15th comes from the approved plan's fixture. No run has shown me any of them; see answers 7 and 10.",
          "wrong_implementation": "A stub returning None fails the 11 non-null cases. Reusing the unchanged `normalize_host` fails \"tube.example:9000\" (port dropped, giving \"tube.example\"), \"https://[::1]:8080/\" (gives \"::1\" with no brackets), \"https://b\u00fccher.example/\" (no punycode) and \"https://tube.example./\" (dot stripped, giving \"tube.example\"); I got this from reading moderation.py:39-63, not from a run. Bare `strip().lower()` fails every URL-form case and every dotted case. Stripping the dot in branches 2 and 3 fails the \"https://tube.example./\" case."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_10_normalise_instance_hosts_phase1.py:47-48 \u2014 `tests/active/host_tokens.json`, read at run time, has exactly 15 entries, and its {input: expected} map equals PINNED (JSON null == None)",
          "expected": "15 entries, and a map equal to PINNED. This makes \"each fixture pair\" in C1 exactly the pairs that line 53 checks.",
          "wrong_implementation": "A fixture written to match the port's output would let line 53 and a fixture-driven test pass by construction. Such a fixture gives a different map here: \"tube.example\" for \"tube.example:9000\", \"::1\" for the IPv6 input, \"b\u00fccher.example\" for the IDN input. A fixture holding only the 14 required pairs, or one with a duplicated or extra pair, gives a different count or map."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "`normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_10_normalise_instance_hosts_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_10_normalise_instance_hosts_phase1.py  16 failed                              0.0s\n  ----------------------------------------------------\n  total                                                 16 failed                              0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_10_normalise_instance_hosts_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "test_10_normalise_instance_hosts_phase2.py:160 \u2014 node running the real dist returns exactly PINNED for all 15 inputs. :163 \u2014 the fixture's pairs are exactly PINNED. :169 \u2014 the durable crawler test reports passed on this tree. :184/:185 \u2014 for each of the 15 fixture inputs in turn, with a current dist wrong on that input alone (control :180), the durable test reports failure and the message contains `wrong-host.invalid`. :197/:198 \u2014 with the realistic `.toLowerCase()` removal, it fails naming 'Tube.Example'.",
          "expected": ":160 and :163 equality holds. :169 \"passed\". :184 \"failure\" and :185 true for every one of the 15 parametrized inputs. :197 \"failure\" with 'Tube.Example' in the message.",
          "wrong_implementation": "A durable crawler test that compares only some fixture pairs (observed with the `subset` variant, which drops the last pair): :184 reads \"passed\" for `'https://tube.example./'`. One that never compares dist's output (`no_compare`): :184 reads \"passed\" for all 15. One that skips or does not exist: :169 reads \"skipped\"/\"not collected\". A fixture that has drifted from the requirements: :163 goes red."
        },
        {
          "clause": "C2",
          "assertion": "test_10_normalise_instance_hosts_phase2.py:205/:206 (no node), :211/:212 (missing dist), :222/:223 (src committed after dist, dist newer on disk), :253/:254 (uncommitted src edit, equal commit times), :262/:263 (dist has no history and is older): each asserts outcome == \"failure\" and the build hint in the junit message. :269 fails without git. Contrasts: :232 and :242 assert \"passed\" when dist was committed after src, or at the same time as a clean src, though older on disk. :186 and :199 assert that a current-but-wrong dist is not reported as stale.",
          "expected": "\"failure\" with BUILD_HINT in the message in each stale, missing or no-node scenario. \"passed\" at :232 and :242. No BUILD_HINT at :186 and :199.",
          "wrong_implementation": "pytest.skip on a missing node: :205 reads \"skipped\". Mtime-only staleness: :222 reads \"passed\", and :232 and :242 read \"failure\". Commit-time-only staleness: :253 and :262 read \"passed\". A >= commit-time rule: :242 reads \"failure\". A test that always fails with the hint: :169 and :232 read \"failure\"."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "`dist/host-filters.js` run under node returns each fixture pair's expected value."
        },
        {
          "id": "C2",
          "text": "A missing node, a missing dist or a stale dist makes the crawler test fail rather than skip."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_10_normalise_instance_hosts_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_10_normalise_instance_hosts_phase2.py  25 failed, 1 passed                    0.0s\n  ----------------------------------------------------\n  total                                                 25 failed, 1 passed                    5.1s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_10_normalise_instance_hosts_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_10_normalise_instance_hosts_phase3.py:44, :48, :49 \u2014 fetch_hosts([\"https://Tube.Example/\", \"tube.example\"]) == {\"tube.example\"}; then sync_hosts on a fresh tmp_path schema == (1, 0, 1); then the instances table holds exactly [(\"tube.example\",)]",
          "expected": "{\"tube.example\"}, then (1, 0, 1), then [(\"tube.example\",)]",
          "wrong_implementation": "Strip-and-lowercase only, which is the pre-phase code. On a run it returned {\"https://tube.example/\", \"tube.example\"}, and syncing that set gives (2, 0, 2) and two rows (the probe observed SYNC_OLD (2, 0, 2))."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_10_normalise_instance_hosts_phase3.py:58, :59 \u2014 fetch_hosts and fetch_join_hosts, fed the same {\"data\": [...]} payload (\"\", \"   \", \".\", \"https://\", \"tube.example.\", \"https://Other.Example/videos\"), each return exactly {\"tube.example\", \"other.example\"}",
          "expected": "{\"tube.example\", \"other.example\"} from both fetchers",
          "wrong_implementation": "Pre-phase strip/lower in either job. On a run it returned {\".\", \"https://\", \"tube.example.\", \"https://other.example/videos\"}. Also excluded: updater-worker left on its own normaliser while sync-whitelist is fixed, which fails :59 on its own."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "`fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`, which `sync_hosts` stores as one row."
        },
        {
          "id": "C2",
          "text": "Entries that normalise to None are dropped, and `fetch_join_hosts` returns the same host set as `fetch_hosts`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_10_normalise_instance_hosts_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_10_normalise_instance_hosts_phase3.py  3 failed                               0.0s\n  ----------------------------------------------------\n  total                                                 3 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_10_normalise_instance_hosts_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this; nearest entry is hardcoded-spec-mirror (rules/shape.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase1.py:48\n   assert {pair[\"input\"]: pair[\"expected\"] for pair in pairs} == PINNED  # C1\n   This compares a JSON test-data file to the inline `PINNED` literal. If one changes, the other\n   must change too, which is the lockstep `hardcoded-spec-mirror <why_bad>` describes. But that\n   entry's <how_to_spot> covers a *code constant*, and `host_tokens.json` is a test fixture, so\n   the entry does not apply as written. I am reporting it because no rule covers mirroring test\n   data. The assertion itself is at the correct rung: it parses the JSON and checks typed values\n   (rung 4) against a structured artifact.\n\nPREDICTED FAILURE\nAll 15 parametrised cases of `test_normalize_host_token_returns_pinned_value` fail at line 53\nwith AttributeError on `moderation.normalize_host_token`, because `engine/server/data/moderation.py`\ndoes not define it. `test_fixture_holds_exactly_the_pinned_pairs` fails at line 46 with\nFileNotFoundError on `FIXTURE.read_text`, because `tests/active/host_tokens.json` does not exist yet.\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/host_tokens.json` and `tests/active/test_host_normalisation.py`\n   as NEW. Neither exists yet, so I could not read them. Line 48 was assessed from the test's\n   side only.\n2. `fixtures_path` was not supplied. The test uses no pytest fixtures other than `parametrize`.\n   The only conftest found (`tests/active/conftest.py`) does not cover `tests/tmp/`, so I did not read it.\n```\n\nNotes on the passes behind the verdict (not part of the gate record):\n\n- **Anti-patterns:**\n  - None of the grep entries apply (`doc-lint-grep`, `section-scoped-substring-grep`, `whole-file-source-name-grep`): no `.md` file is read.\n  - Not `tautological-assertion`: every expected value is an independent literal (lines 26\u201340), not computed.\n  - Not `echoed-literal`: the value passes through the production `normalize_host_token` at line 53.\n  - Not `single-value-pin`: 15 inputs, most of which are not fixed points (`\" Tube.Example \"` \u2192 `\"tube.example\"`), so identity fails.\n  - Not `absence-only-assertion`: the four `None` cases (lines 36\u201339) sit beside eleven positive cases.\n- **Ladder:** line 53 calls the function directly and checks its return value (rung 1), which is the highest rung and fits a pure function. Line 48 is rung 4, matched to a structured JSON artifact. Nothing lands on the anti-rung, and there is no downshift.\n- **Stub question:** the test would catch each plausible wrong implementation:\n\n  | Wrong implementation | Cases that fail |\n  |---|---|\n  | Hard-coded `\"tube.example\"` | The `None` cases, `\"tube.example:9000\"`, `\"[::1]\"` and the punycode case |\n  | `return None` | The 11 positive cases |\n  | Identity | Line 26 |\n  | Stripping every trailing dot | Line 40 (`\"https://tube.example./\"` \u2192 `\"tube.example.\"`) |",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (9 clauses: 2 must_prove, 5 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `normalize_host_token` returns each fixture pair's expected value | :53, with :47 and :48 | :53 excludes a port that gets any of the 11 non-null pinned pairs wrong (e.g. keeps `:8080`, drops `:9000`, leaves `B\u00fccher` un-punycoded, strips the dot in `tube.example./`). :47 and :48 exclude a fixture holding pairs other than those checked, so \"each fixture pair\" is covered too | CARRIED |\n| C1b | must_prove | None where the expected value is null | :53 (cases `''`, `'   '`, `'.'`, `'https://'`) | a port returning `\"\"`, `\".\"` or the raw input instead of None. `==` against None does not accept `\"\"` | CARRIED |\n| D1 | docstring | \"the Engine's port of the crawler's `normalizeHostToken`\" | :53 | a port that differs from the crawler on any pinned value (the pinned WHATWG values stand in for the crawler; the crawler itself is not run) | CARRIED |\n| D2 | docstring | fixture \"holds exactly the 15 input -> expected pairs pinned by the requirements\" | :47, :48 | a fixture with a missing, extra, duplicated or altered pair. :47 catches the duplicate that the dict at :48 would collapse | CARRIED |\n| D3 | docstring | \"WHATWG `URL.hostname` values, null for None\" | :48 | a fixture that writes `\"\"` or `\"null\"` in place of JSON null, or non-WHATWG values | CARRIED |\n| D4 | docstring | \"cannot drift to match the port\" | :48 against the hard-coded `PINNED` at :25-41 | a fixture edited to fit the port's output. `PINNED` is written independently of the fixture | CARRIED |\n| D5 | docstring | \"for every pinned pair \u2026 returns the expected value, and None where it is null\" | :53 (parametrised over all 15) | as C1a and C1b | CARRIED |\n| N1 | name | `test_fixture_holds_exactly_the_pinned_pairs` | :47, :48 | as D2 | CARRIED |\n| N2 | name | `test_normalize_host_token_returns_pinned_value` | :53 | as C1a | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase1.py:25\n   The pinned set covers empty, whitespace-only, `.`, and a scheme with no host. It has no malformed URL that the parser rejects (for example `http://[`, where `urlparse` raises `ValueError`, the error the existing `normalize_host` at moderation.py:50-53 catches). It also has no `None` input, which the sibling `normalize_host` accepts (moderation.py:39-42). These cases are outside C1's pinned pairs, so this does not block.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/host_tokens.json` and `tests/active/test_host_normalisation.py`, but neither exists in the worktree. The fixture's contents could not be read, so D2 and D3 were judged only from what :47 and :48 would enforce. The test does not reference `test_host_normalisation.py`, and that file was not assessed.\n2. `normalize_host_token` is not yet defined in `engine/server/data/moderation.py` (the only similar function is `normalize_host` at :39). Its accepted input types and failure behaviour could not be read from code. Bounds were judged from the pinned table and the sibling function.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this; nearest entry is hardcoded-spec-mirror (rules/shape.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase1.py:48\n   assert {pair[\"input\"]: pair[\"expected\"] for pair in pairs} == PINNED  # C1\n   This compares a JSON test-data file to the inline `PINNED` literal. If one changes, the other\n   must change too, which is the lockstep `hardcoded-spec-mirror <why_bad>` describes. But that\n   entry's <how_to_spot> covers a *code constant*, and `host_tokens.json` is a test fixture, so\n   the entry does not apply as written. I am reporting it because no rule covers mirroring test\n   data. The assertion itself is at the correct rung: it parses the JSON and checks typed values\n   (rung 4) against a structured artifact.\n\nPREDICTED FAILURE\nAll 15 parametrised cases of `test_normalize_host_token_returns_pinned_value` fail at line 53\nwith AttributeError on `moderation.normalize_host_token`, because `engine/server/data/moderation.py`\ndoes not define it. `test_fixture_holds_exactly_the_pinned_pairs` fails at line 46 with\nFileNotFoundError on `FIXTURE.read_text`, because `tests/active/host_tokens.json` does not exist yet.\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/host_tokens.json` and `tests/active/test_host_normalisation.py`\n   as NEW. Neither exists yet, so I could not read them. Line 48 was assessed from the test's\n   side only.\n2. `fixtures_path` was not supplied. The test uses no pytest fixtures other than `parametrize`.\n   The only conftest found (`tests/active/conftest.py`) does not cover `tests/tmp/`, so I did not read it.\n```\n\nNotes on the passes behind the verdict (not part of the gate record):\n\n- **Anti-patterns:**\n  - None of the grep entries apply (`doc-lint-grep`, `section-scoped-substring-grep`, `whole-file-source-name-grep`): no `.md` file is read.\n  - Not `tautological-assertion`: every expected value is an independent literal (lines 26\u201340), not computed.\n  - Not `echoed-literal`: the value passes through the production `normalize_host_token` at line 53.\n  - Not `single-value-pin`: 15 inputs, most of which are not fixed points (`\" Tube.Example \"` \u2192 `\"tube.example\"`), so identity fails.\n  - Not `absence-only-assertion`: the four `None` cases (lines 36\u201339) sit beside eleven positive cases.\n- **Ladder:** line 53 calls the function directly and checks its return value (rung 1), which is the highest rung and fits a pure function. Line 48 is rung 4, matched to a structured JSON artifact. Nothing lands on the anti-rung, and there is no downshift.\n- **Stub question:** the test would catch each plausible wrong implementation:\n\n  | Wrong implementation | Cases that fail |\n  |---|---|\n  | Hard-coded `\"tube.example\"` | The `None` cases, `\"tube.example:9000\"`, `\"[::1]\"` and the punycode case |\n  | `return None` | The 11 positive cases |\n  | Identity | Line 26 |\n  | Stripping every trailing dot | Line 40 (`\"https://tube.example./\"` \u2192 `\"tube.example.\"`) |\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (9 clauses: 2 must_prove, 5 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `normalize_host_token` returns each fixture pair's expected value | :53, with :47 and :48 | :53 excludes a port that gets any of the 11 non-null pinned pairs wrong (e.g. keeps `:8080`, drops `:9000`, leaves `B\u00fccher` un-punycoded, strips the dot in `tube.example./`). :47 and :48 exclude a fixture holding pairs other than those checked, so \"each fixture pair\" is covered too | CARRIED |\n| C1b | must_prove | None where the expected value is null | :53 (cases `''`, `'   '`, `'.'`, `'https://'`) | a port returning `\"\"`, `\".\"` or the raw input instead of None. `==` against None does not accept `\"\"` | CARRIED |\n| D1 | docstring | \"the Engine's port of the crawler's `normalizeHostToken`\" | :53 | a port that differs from the crawler on any pinned value (the pinned WHATWG values stand in for the crawler; the crawler itself is not run) | CARRIED |\n| D2 | docstring | fixture \"holds exactly the 15 input -> expected pairs pinned by the requirements\" | :47, :48 | a fixture with a missing, extra, duplicated or altered pair. :47 catches the duplicate that the dict at :48 would collapse | CARRIED |\n| D3 | docstring | \"WHATWG `URL.hostname` values, null for None\" | :48 | a fixture that writes `\"\"` or `\"null\"` in place of JSON null, or non-WHATWG values | CARRIED |\n| D4 | docstring | \"cannot drift to match the port\" | :48 against the hard-coded `PINNED` at :25-41 | a fixture edited to fit the port's output. `PINNED` is written independently of the fixture | CARRIED |\n| D5 | docstring | \"for every pinned pair \u2026 returns the expected value, and None where it is null\" | :53 (parametrised over all 15) | as C1a and C1b | CARRIED |\n| N1 | name | `test_fixture_holds_exactly_the_pinned_pairs` | :47, :48 | as D2 | CARRIED |\n| N2 | name | `test_normalize_host_token_returns_pinned_value` | :53 | as C1a | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase1.py:25\n   The pinned set covers empty, whitespace-only, `.`, and a scheme with no host. It has no malformed URL that the parser rejects (for example `http://[`, where `urlparse` raises `ValueError`, the error the existing `normalize_host` at moderation.py:50-53 catches). It also has no `None` input, which the sibling `normalize_host` accepts (moderation.py:39-42). These cases are outside C1's pinned pairs, so this does not block.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/host_tokens.json` and `tests/active/test_host_normalisation.py`, but neither exists in the worktree. The fixture's contents could not be read, so D2 and D3 were judged only from what :47 and :48 would enforce. The test does not reference `test_host_normalisation.py`, and that file was not assessed.\n2. `normalize_host_token` is not yet defined in `engine/server/data/moderation.py` (the only similar function is `normalize_host` at :39). Its accepted input types and failure behaviour could not be read from code. Bounds were judged from the pinned table and the sibling function.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`normalize_host_token` returns each fixture pair's expected value",
            "assertion": ":53, with :47 and :48",
            "excludes": ":53 excludes a port that gets any of the 11 non-null pinned pairs wrong (e.g. keeps `:8080`, drops `:9000`, leaves `B\u00fccher` un-punycoded, strips the dot in `tube.example./`). :47 and :48 exclude a fixture holding pairs other than those checked, so \"each fixture pair\" is covered too",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "None where the expected value is null",
            "assertion": ":53 (cases `''`, `'   '`, `'.'`, `'https://'`)",
            "excludes": "a port returning `\"\"`, `\".\"` or the raw input instead of None. `==` against None does not accept `\"\"`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"the Engine's port of the crawler's `normalizeHostToken`\"",
            "assertion": ":53",
            "excludes": "a port that differs from the crawler on any pinned value (the pinned WHATWG values stand in for the crawler; the crawler itself is not run)",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "fixture \"holds exactly the 15 input -> expected pairs pinned by the requirements\"",
            "assertion": ":47, :48",
            "excludes": "a fixture with a missing, extra, duplicated or altered pair. :47 catches the duplicate that the dict at :48 would collapse",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"WHATWG `URL.hostname` values, null for None\"",
            "assertion": ":48",
            "excludes": "a fixture that writes `\"\"` or `\"null\"` in place of JSON null, or non-WHATWG values",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"cannot drift to match the port\"",
            "assertion": ":48 against the hard-coded `PINNED` at :25-41",
            "excludes": "a fixture edited to fit the port's output. `PINNED` is written independently of the fixture",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"for every pinned pair \u2026 returns the expected value, and None where it is null\"",
            "assertion": ":53 (parametrised over all 15)",
            "excludes": "as C1a and C1b",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_fixture_holds_exactly_the_pinned_pairs`",
            "assertion": ":47, :48",
            "excludes": "as D2",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_normalize_host_token_returns_pinned_value`",
            "assertion": ":53",
            "excludes": "as C1a",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_10_normalise_instance_hosts_phase2.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:228\n   assert \"git\" in message  # C2\n   The test's other failure checks look for the exact BUILD_HINT string. This one only looks\n   for the three letters \"git\" anywhere in junit's message. It still separates a durable test\n   that never calls git, because that test comes out \"passed\" and line 227 turns red. But any\n   failure whose message happens to include \"git\" in a path or another word also passes.\n   Matching the durable test's own git-missing wording would pin it the way lines 174/180 pin\n   BUILD_HINT. No <anti_pattern> entry names this, so it is a Recommendation only.\n\nPREDICTED FAILURE\nFails at line 154 in test_durable_crawler_test_passes_on_this_tree: `outcome == \"passed\"` gets\n\"not collected\", because tests/active/test_host_normalisation.py has no test matching\n`-k crawler_dist` yet. Lines 165, 173, 179, 190, 200, 211, 220 and 227 fail the same way on\ntheir outcome assertion. Line 148 (the premise test) is expected to pass as things stand.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The durable file imports ROOT from `conftest`, which was\n   not read. The stub question does not depend on it, because the checkpoint only sees the\n   durable test through junit outcome and message.\n2. Whether node and git are on PATH in the environment that will run this could not be checked\n   by reading. The prediction for line 148 assumes both are present. engine/crawler/dist/host-filters.js\n   was confirmed to exist, and it contains LOWERCASE_LINE exactly once, which the line-160\n   precondition needs.\n\nAnti-patterns pass: none of the anti-pattern entries applies. No .md file is read.\nPINNED (line 27) holds hand-written expected values set against node's output, not a mirror of\na code constant, and nothing in the test works them out again. The negative at line 167 is\npaired with positive checks at lines 165\u2013166. The wrong-value scenario (157) and the\nthis-tree pass (151) read the same observable at two inputs, so there is no single-value pin.\n\nLadder pass: rung 2 (node subprocess, and pytest run as a subprocess) with a junit XML parse.\nThat is the highest rung available: the JS function has no Python entry point, and \"fails\nrather than skips\" can only be observed from outside the durable test's own pytest run. No\ndownshift, so no comment is required.\n\nStub question: this file does not pass against a stub durable test. With no test present it\ngets \"not collected\". A test that always fails is caught at 154/200. A test that always calls\npytest.fail(BUILD_HINT) is caught at 154. One that only checks presence without comparing\nvalues is caught at 165\u2013166. One that goes by mtime alone is caught at 154 (this tree) and\n190. One that goes by commit time alone is caught at 211 and 220. One that skips gets\n\"skipped\" and is caught at every `outcome ==` line.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (29 clauses: 7 must_prove, 12 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"`dist/host-filters.js` run under node returns\" the expected value for every pinned input | :148 | a dist that gets any one of the 15 inputs wrong or leaves one out (compares the whole dict; `zip` truncation would lose a key and break equality) | CARRIED |\n| C1b | must_prove | the crawler test holds dist to \"each fixture pair\" | :154, :165, :166 | a crawler test that never runs dist, skips, or compares only the Python port. It does not exclude a crawler test that checks a subset of pairs: the one mutation breaks only `\" Tube.Example \"` | UNCARRIED |\n| C2a | must_prove | \"a missing node\" makes the crawler test fail rather than skip | :173, :174 | a skip, an error, no test collected, or a failure without the build hint when node is off PATH. :154 is the node-present contrast | CARRIED |\n| C2b | must_prove | \"a missing dist\" fails rather than skips | :179, :180 | a skip, error or silent pass when DIST does not exist | CARRIED |\n| C2c1 | must_prove | \"a stale dist\" (src committed after dist) fails | :190, :191 | a check that only compares mtimes, since dist is newer on disk here (:188), and a skip | CARRIED |\n| C2c2 | must_prove | \"a stale dist\" (uncommitted src edit newer on disk) fails | :211, :212 | a check that only compares commit times, since the commit times are equal (:206) | CARRIED |\n| C2c3 | must_prove | \"a stale dist\" (dist has no history and is older on disk) fails | :220, :221 | a check that skips or passes when git has no commit time for dist | CARRIED |\n| D1 | docstring | \"imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values\" | :146, :148 | a dist that differs on any pinned input | CARRIED |\n| D2 | docstring | \"so with phase 1 the Python port equals the crawler on the fixture\" | none | nothing: `PINNED` is a hand copy, and no assertion ties it to `tests/active/host_tokens.json` | UNCARRIED |\n| D3 | docstring | \"passes on this tree\" | :154 | a skipping, erroring or missing crawler test (\"not collected\" \u2260 \"passed\") | CARRIED |\n| D4 | docstring | \"whose dist is committed with src but is older on disk\" | none | a premise the test never checks: nothing asserts the tree's commit or mtime state | UNCARRIED |\n| D5 | docstring | \"fails on a dist that is current but returns a wrong value for one input\" | :160, :165, :166, :167 | a crawler test that does not compare dist's output, or that reports this as staleness (:167) | CARRIED |\n| D6 | docstring | fails, never skips, with the build hint \"when node is off PATH\" | :173, :174 | a skip, or a failure without the hint | CARRIED |\n| D7 | docstring | \"... when dist is missing\" | :179, :180 | same, for a missing dist | CARRIED |\n| D8 | docstring | \"... when src was committed after dist\" | :190, :191 | a check that only compares mtimes | CARRIED |\n| D9 | docstring | \"... when src has an uncommitted edit newer on disk than dist\" | :211, :212 | a check that only compares commit times | CARRIED |\n| D10 | docstring | \"... when dist has no history and is older on disk than src\" | :220, :221 | a skip or pass when dist has no commit history | CARRIED |\n| D11 | docstring | \"it fails when git is off PATH\" | :227 | a skip or pass without git | CARRIED |\n| D12 | docstring | \"passes when dist was committed after src though older on disk\" | :200 | a crawler test that always fails, or one that only compares mtimes | CARRIED |\n| N1 | name | `test_crawler_dist_under_node_returns_pinned_values` | :148 | a dist with any wrong pinned value | CARRIED |\n| N2 | name | `test_durable_crawler_test_passes_on_this_tree` | :154 | a skipping or missing crawler test | CARRIED |\n| N3 | name | `..._fails_on_current_dist_with_one_wrong_value` | :165, :166 | a crawler test that does not compare values | CARRIED |\n| N4 | name | `..._fails_loudly_without_node` | :173, :174 | a skip, or a failure with no hint | CARRIED |\n| N5 | name | `..._fails_loudly_when_dist_is_missing` | :179, :180 | same | CARRIED |\n| N6 | name | `..._fails_loudly_when_src_committed_after_dist` | :190, :191 | a check that only compares mtimes | CARRIED |\n| N7 | name | `..._passes_when_dist_committed_after_src_though_older_on_disk` | :200 | a check that always fails or only compares mtimes | CARRIED |\n| N8 | name | `..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist` | :211, :212 | a check that only compares commit times | CARRIED |\n| N9 | name | `..._fails_loudly_when_dist_has_no_history_and_is_older` | :220, :221 | a skip or pass with no history | CARRIED |\n| N10 | name | `..._fails_without_git` | :227 | a skip or pass without git | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:161, :165\u2013166\n   `dist.write_text(text.replace(LOWERCASE_LINE, \"const raw = value.trim();\"), encoding=\"utf-8\")`\n   `assert \"'Tube.Example'\" in message  # C1`\n   C1 says the crawler test holds dist to *each* fixture pair's expected value. The checkpoint shows this through the crawler test only twice: it passes on the real dist (:154), and it fails when one line is mutated. That mutation breaks exactly one of the 15 pairs (`\" Tube.Example \"`), as the comment at :66 says. So a crawler test that checks only that input, or any subset containing it, passes :154, :165 and :166 alike. This is the \"X per Y needs a second Y\" case in `<whole-claim>`: one wrong pair proves the test compares values, not that it compares every pair. :148 checks every pinned value, but it checks them against the real dist directly, not through the code under test. Its own comment at :143 calls it a \"Premise, true before the phase\", so it cannot carry the crawler test's coverage.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:26\u201343\n   D2 is UNCARRIED. The docstring says \"the Python port equals the crawler on the fixture\", but `PINNED` is written out \"independently of the fixture\" and never compared with `tests/active/host_tokens.json`. The two match on disk today, but nothing here would notice if they drifted apart.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:152\u2013154\n   D4 is UNCARRIED. \"whose dist is committed with src but is older on disk\" describes the real tree, and nothing asserts it. If the tree's state changes, :154 still passes and no longer tests what the docstring says.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:151\u2013154\n   The equal-commit-time, no-uncommitted-edit, dist-older-on-disk boundary is only reached through the real tree, whose state is unasserted (D4). No scenario in a controlled repo, like the ones built at :194\u2013221, pins it.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. `tests/active/conftest.py` was read because the code under test imports `ROOT` from it, and it has no effect on this test's claims.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:228\n   assert \"git\" in message  # C2\n   The test's other failure checks look for the exact BUILD_HINT string. This one only looks\n   for the three letters \"git\" anywhere in junit's message. It still separates a durable test\n   that never calls git, because that test comes out \"passed\" and line 227 turns red. But any\n   failure whose message happens to include \"git\" in a path or another word also passes.\n   Matching the durable test's own git-missing wording would pin it the way lines 174/180 pin\n   BUILD_HINT. No <anti_pattern> entry names this, so it is a Recommendation only.\n\nPREDICTED FAILURE\nFails at line 154 in test_durable_crawler_test_passes_on_this_tree: `outcome == \"passed\"` gets\n\"not collected\", because tests/active/test_host_normalisation.py has no test matching\n`-k crawler_dist` yet. Lines 165, 173, 179, 190, 200, 211, 220 and 227 fail the same way on\ntheir outcome assertion. Line 148 (the premise test) is expected to pass as things stand.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The durable file imports ROOT from `conftest`, which was\n   not read. The stub question does not depend on it, because the checkpoint only sees the\n   durable test through junit outcome and message.\n2. Whether node and git are on PATH in the environment that will run this could not be checked\n   by reading. The prediction for line 148 assumes both are present. engine/crawler/dist/host-filters.js\n   was confirmed to exist, and it contains LOWERCASE_LINE exactly once, which the line-160\n   precondition needs.\n\nAnti-patterns pass: none of the anti-pattern entries applies. No .md file is read.\nPINNED (line 27) holds hand-written expected values set against node's output, not a mirror of\na code constant, and nothing in the test works them out again. The negative at line 167 is\npaired with positive checks at lines 165\u2013166. The wrong-value scenario (157) and the\nthis-tree pass (151) read the same observable at two inputs, so there is no single-value pin.\n\nLadder pass: rung 2 (node subprocess, and pytest run as a subprocess) with a junit XML parse.\nThat is the highest rung available: the JS function has no Python entry point, and \"fails\nrather than skips\" can only be observed from outside the durable test's own pytest run. No\ndownshift, so no comment is required.\n\nStub question: this file does not pass against a stub durable test. With no test present it\ngets \"not collected\". A test that always fails is caught at 154/200. A test that always calls\npytest.fail(BUILD_HINT) is caught at 154. One that only checks presence without comparing\nvalues is caught at 165\u2013166. One that goes by mtime alone is caught at 154 (this tree) and\n190. One that goes by commit time alone is caught at 211 and 220. One that skips gets\n\"skipped\" and is caught at every `outcome ==` line.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (29 clauses: 7 must_prove, 12 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"`dist/host-filters.js` run under node returns\" the expected value for every pinned input | :148 | a dist that gets any one of the 15 inputs wrong or leaves one out (compares the whole dict; `zip` truncation would lose a key and break equality) | CARRIED |\n| C1b | must_prove | the crawler test holds dist to \"each fixture pair\" | :154, :165, :166 | a crawler test that never runs dist, skips, or compares only the Python port. It does not exclude a crawler test that checks a subset of pairs: the one mutation breaks only `\" Tube.Example \"` | UNCARRIED |\n| C2a | must_prove | \"a missing node\" makes the crawler test fail rather than skip | :173, :174 | a skip, an error, no test collected, or a failure without the build hint when node is off PATH. :154 is the node-present contrast | CARRIED |\n| C2b | must_prove | \"a missing dist\" fails rather than skips | :179, :180 | a skip, error or silent pass when DIST does not exist | CARRIED |\n| C2c1 | must_prove | \"a stale dist\" (src committed after dist) fails | :190, :191 | a check that only compares mtimes, since dist is newer on disk here (:188), and a skip | CARRIED |\n| C2c2 | must_prove | \"a stale dist\" (uncommitted src edit newer on disk) fails | :211, :212 | a check that only compares commit times, since the commit times are equal (:206) | CARRIED |\n| C2c3 | must_prove | \"a stale dist\" (dist has no history and is older on disk) fails | :220, :221 | a check that skips or passes when git has no commit time for dist | CARRIED |\n| D1 | docstring | \"imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values\" | :146, :148 | a dist that differs on any pinned input | CARRIED |\n| D2 | docstring | \"so with phase 1 the Python port equals the crawler on the fixture\" | none | nothing: `PINNED` is a hand copy, and no assertion ties it to `tests/active/host_tokens.json` | UNCARRIED |\n| D3 | docstring | \"passes on this tree\" | :154 | a skipping, erroring or missing crawler test (\"not collected\" \u2260 \"passed\") | CARRIED |\n| D4 | docstring | \"whose dist is committed with src but is older on disk\" | none | a premise the test never checks: nothing asserts the tree's commit or mtime state | UNCARRIED |\n| D5 | docstring | \"fails on a dist that is current but returns a wrong value for one input\" | :160, :165, :166, :167 | a crawler test that does not compare dist's output, or that reports this as staleness (:167) | CARRIED |\n| D6 | docstring | fails, never skips, with the build hint \"when node is off PATH\" | :173, :174 | a skip, or a failure without the hint | CARRIED |\n| D7 | docstring | \"... when dist is missing\" | :179, :180 | same, for a missing dist | CARRIED |\n| D8 | docstring | \"... when src was committed after dist\" | :190, :191 | a check that only compares mtimes | CARRIED |\n| D9 | docstring | \"... when src has an uncommitted edit newer on disk than dist\" | :211, :212 | a check that only compares commit times | CARRIED |\n| D10 | docstring | \"... when dist has no history and is older on disk than src\" | :220, :221 | a skip or pass when dist has no commit history | CARRIED |\n| D11 | docstring | \"it fails when git is off PATH\" | :227 | a skip or pass without git | CARRIED |\n| D12 | docstring | \"passes when dist was committed after src though older on disk\" | :200 | a crawler test that always fails, or one that only compares mtimes | CARRIED |\n| N1 | name | `test_crawler_dist_under_node_returns_pinned_values` | :148 | a dist with any wrong pinned value | CARRIED |\n| N2 | name | `test_durable_crawler_test_passes_on_this_tree` | :154 | a skipping or missing crawler test | CARRIED |\n| N3 | name | `..._fails_on_current_dist_with_one_wrong_value` | :165, :166 | a crawler test that does not compare values | CARRIED |\n| N4 | name | `..._fails_loudly_without_node` | :173, :174 | a skip, or a failure with no hint | CARRIED |\n| N5 | name | `..._fails_loudly_when_dist_is_missing` | :179, :180 | same | CARRIED |\n| N6 | name | `..._fails_loudly_when_src_committed_after_dist` | :190, :191 | a check that only compares mtimes | CARRIED |\n| N7 | name | `..._passes_when_dist_committed_after_src_though_older_on_disk` | :200 | a check that always fails or only compares mtimes | CARRIED |\n| N8 | name | `..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist` | :211, :212 | a check that only compares commit times | CARRIED |\n| N9 | name | `..._fails_loudly_when_dist_has_no_history_and_is_older` | :220, :221 | a skip or pass with no history | CARRIED |\n| N10 | name | `..._fails_without_git` | :227 | a skip or pass without git | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:161, :165\u2013166\n   `dist.write_text(text.replace(LOWERCASE_LINE, \"const raw = value.trim();\"), encoding=\"utf-8\")`\n   `assert \"'Tube.Example'\" in message  # C1`\n   C1 says the crawler test holds dist to *each* fixture pair's expected value. The checkpoint shows this through the crawler test only twice: it passes on the real dist (:154), and it fails when one line is mutated. That mutation breaks exactly one of the 15 pairs (`\" Tube.Example \"`), as the comment at :66 says. So a crawler test that checks only that input, or any subset containing it, passes :154, :165 and :166 alike. This is the \"X per Y needs a second Y\" case in `<whole-claim>`: one wrong pair proves the test compares values, not that it compares every pair. :148 checks every pinned value, but it checks them against the real dist directly, not through the code under test. Its own comment at :143 calls it a \"Premise, true before the phase\", so it cannot carry the crawler test's coverage.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:26\u201343\n   D2 is UNCARRIED. The docstring says \"the Python port equals the crawler on the fixture\", but `PINNED` is written out \"independently of the fixture\" and never compared with `tests/active/host_tokens.json`. The two match on disk today, but nothing here would notice if they drifted apart.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:152\u2013154\n   D4 is UNCARRIED. \"whose dist is committed with src but is older on disk\" describes the real tree, and nothing asserts it. If the tree's state changes, :154 still passes and no longer tests what the docstring says.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:151\u2013154\n   The equal-commit-time, no-uncommitted-edit, dist-older-on-disk boundary is only reached through the real tree, whose state is unasserted (D4). No scenario in a controlled repo, like the ones built at :194\u2013221, pins it.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. `tests/active/conftest.py` was read because the code under test imports `ROOT` from it, and it has no effect on this test's claims.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"`dist/host-filters.js` run under node returns\" the expected value for every pinned input",
            "assertion": ":148",
            "excludes": "a dist that gets any one of the 15 inputs wrong or leaves one out (compares the whole dict; `zip` truncation would lose a key and break equality)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the crawler test holds dist to \"each fixture pair\"",
            "assertion": ":154, :165, :166",
            "excludes": "a crawler test that never runs dist, skips, or compares only the Python port. It does not exclude a crawler test that checks a subset of pairs: the one mutation breaks only `\" Tube.Example \"`",
            "status": "UNCARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"a missing node\" makes the crawler test fail rather than skip",
            "assertion": ":173, :174",
            "excludes": "a skip, an error, no test collected, or a failure without the build hint when node is off PATH. :154 is the node-present contrast",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"a missing dist\" fails rather than skips",
            "assertion": ":179, :180",
            "excludes": "a skip, error or silent pass when DIST does not exist",
            "status": "CARRIED"
          },
          {
            "id": "C2c1",
            "source": "must_prove",
            "clause": "\"a stale dist\" (src committed after dist) fails",
            "assertion": ":190, :191",
            "excludes": "a check that only compares mtimes, since dist is newer on disk here (:188), and a skip",
            "status": "CARRIED"
          },
          {
            "id": "C2c2",
            "source": "must_prove",
            "clause": "\"a stale dist\" (uncommitted src edit newer on disk) fails",
            "assertion": ":211, :212",
            "excludes": "a check that only compares commit times, since the commit times are equal (:206)",
            "status": "CARRIED"
          },
          {
            "id": "C2c3",
            "source": "must_prove",
            "clause": "\"a stale dist\" (dist has no history and is older on disk) fails",
            "assertion": ":220, :221",
            "excludes": "a check that skips or passes when git has no commit time for dist",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values\"",
            "assertion": ":146, :148",
            "excludes": "a dist that differs on any pinned input",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"so with phase 1 the Python port equals the crawler on the fixture\"",
            "assertion": "none",
            "excludes": "nothing: `PINNED` is a hand copy, and no assertion ties it to `tests/active/host_tokens.json`",
            "status": "UNCARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"passes on this tree\"",
            "assertion": ":154",
            "excludes": "a skipping, erroring or missing crawler test (\"not collected\" \u2260 \"passed\")",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"whose dist is committed with src but is older on disk\"",
            "assertion": "none",
            "excludes": "a premise the test never checks: nothing asserts the tree's commit or mtime state",
            "status": "UNCARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"fails on a dist that is current but returns a wrong value for one input\"",
            "assertion": ":160, :165, :166, :167",
            "excludes": "a crawler test that does not compare dist's output, or that reports this as staleness (:167)",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "fails, never skips, with the build hint \"when node is off PATH\"",
            "assertion": ":173, :174",
            "excludes": "a skip, or a failure without the hint",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"... when dist is missing\"",
            "assertion": ":179, :180",
            "excludes": "same, for a missing dist",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"... when src was committed after dist\"",
            "assertion": ":190, :191",
            "excludes": "a check that only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"... when src has an uncommitted edit newer on disk than dist\"",
            "assertion": ":211, :212",
            "excludes": "a check that only compares commit times",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"... when dist has no history and is older on disk than src\"",
            "assertion": ":220, :221",
            "excludes": "a skip or pass when dist has no commit history",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"it fails when git is off PATH\"",
            "assertion": ":227",
            "excludes": "a skip or pass without git",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"passes when dist was committed after src though older on disk\"",
            "assertion": ":200",
            "excludes": "a crawler test that always fails, or one that only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_crawler_dist_under_node_returns_pinned_values`",
            "assertion": ":148",
            "excludes": "a dist with any wrong pinned value",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_durable_crawler_test_passes_on_this_tree`",
            "assertion": ":154",
            "excludes": "a skipping or missing crawler test",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "`..._fails_on_current_dist_with_one_wrong_value`",
            "assertion": ":165, :166",
            "excludes": "a crawler test that does not compare values",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "`..._fails_loudly_without_node`",
            "assertion": ":173, :174",
            "excludes": "a skip, or a failure with no hint",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "`..._fails_loudly_when_dist_is_missing`",
            "assertion": ":179, :180",
            "excludes": "same",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "`..._fails_loudly_when_src_committed_after_dist`",
            "assertion": ":190, :191",
            "excludes": "a check that only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "`..._passes_when_dist_committed_after_src_though_older_on_disk`",
            "assertion": ":200",
            "excludes": "a check that always fails or only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "`..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist`",
            "assertion": ":211, :212",
            "excludes": "a check that only compares commit times",
            "status": "CARRIED"
          },
          {
            "id": "N9",
            "source": "name",
            "clause": "`..._fails_loudly_when_dist_has_no_history_and_is_older`",
            "assertion": ":220, :221",
            "excludes": "a skip or pass with no history",
            "status": "CARRIED"
          },
          {
            "id": "N10",
            "source": "name",
            "clause": "`..._fails_without_git`",
            "assertion": ":227",
            "excludes": "a skip or pass without git",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:160\n   assert _dist_outputs(REAL_DIST) == PINNED\n   test_crawler_dist_under_node_returns_pinned_values checks the real dist and the fixture,\n   and the phase writes neither. Its comment says it is already true before the phase (line 158),\n   so it will pass against a stub durable test. The file still blocks a stub because every other\n   test runs the durable test. shape.md has no entry for a premise test inside a checkpoint.\n   It is noted here so that nobody reads this test's green result as evidence the phase is done.\n\nPREDICTED FAILURE\nThe durable file tests/active/test_host_normalisation.py has no test matching `-k crawler_dist`\nyet, so `_run_crawler_test` returns \"not collected\" every time.\n- Line 169 fails on `assert outcome == \"passed\", message`.\n- Lines 184, 197, 205, 211, 222, 232, 242, 253, 262 and 269 fail the same way on their\n  `assert outcome == ...` line, and so does each of the 15 parametrized cases at line 184.\n- test_crawler_dist_under_node_returns_pinned_values (lines 157-163) passes.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The checkpoint uses only pytest's built-in `tmp_path`.\n   I did not read the `conftest.py` that the durable file imports `ROOT` from (line 11). Nothing\n   in the checkpoint depends on it.\n2. I read `code_under_test` in its current form. The durable `crawler_dist` test the checkpoint\n   drives does not exist yet, so the stub question was answered from how the checkpoint's\n   assertions are built. That covers the outcome and message checks paired with the \"must pass\"\n   controls at lines 169, 232 and 242, and the 15-input parametrization at line 172.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (29 clauses: 7 must_prove, 12 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"`dist/host-filters.js` run under node returns\" the expected value for every pinned input | :160 | a dist that gets any one of the 15 inputs wrong or leaves one out. The whole dict is compared, so if `zip` truncates, a key goes missing and equality fails | CARRIED |\n| C1b | must_prove | the crawler test holds dist to \"each fixture pair\" | :184, :185 (control :180) | a crawler test that checks only some of the pairs. The test is parametrised over every fixture input (:172), and each run's dist is wrong on that one input only (:180), so leaving out any pair lets one run pass | CARRIED |\n| C2a | must_prove | \"a missing node\" makes the crawler test fail rather than skip | :205, :206 | a skip, an error, no test collected, or a failure without the build hint when node is off PATH | CARRIED |\n| C2b | must_prove | \"a missing dist\" fails rather than skips | :211, :212 | a skip, error or silent pass when DIST does not exist | CARRIED |\n| C2c1 | must_prove | \"a stale dist\" (src committed after dist) fails | :222, :223 | a check that only compares mtimes, because dist is newer on disk here (:220), and a skip | CARRIED |\n| C2c2 | must_prove | \"a stale dist\" (uncommitted src edit newer on disk) fails | :253, :254 | a check that only compares commit times, because the commit times are equal (:247\u2013248) | CARRIED |\n| C2c3 | must_prove | \"a stale dist\" (dist has no history and is older on disk) fails | :262, :263 | a check that skips or passes when git has no commit time for dist | CARRIED |\n| D1 | docstring | \"imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values\" | :160 | a dist that differs on any pinned input | CARRIED |\n| D2 | docstring | \"so with phase 1 the Python port equals the crawler on the fixture\" | :162, :163 (with :160) | a fixture that differs from PINNED, or holds a duplicated input, so it no longer matches the dist's output. The fixture is now pinned to the same pairs the dist is held to | CARRIED |\n| D3 | docstring | \"passes on this tree\" | :169 | a skipping, erroring or missing crawler test (\"not collected\" \u2260 \"passed\") | CARRIED |\n| D4 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D5 | docstring | \"fails, without the build hint, on a current dist that returns a wrong value for one input\" | :184\u2013186, :197\u2013199 | a crawler test that does not compare dist's output, or that reports it as staleness (:186, :199) | CARRIED |\n| D6 | docstring | fails, never skips, with the build hint \"when node is off PATH\" | :205, :206 | a skip, or a failure without the hint | CARRIED |\n| D7 | docstring | \"... when dist is missing\" | :211, :212 | the same, for a missing dist | CARRIED |\n| D8 | docstring | \"... when src was committed after dist\" | :222, :223 | a check that only compares mtimes | CARRIED |\n| D9 | docstring | \"... when src has an uncommitted edit newer on disk than dist\" | :253, :254 | a check that only compares commit times | CARRIED |\n| D10 | docstring | \"... when dist has no history and is older on disk than src\" | :262, :263 | a skip or pass when dist has no commit history | CARRIED |\n| D11 | docstring | \"it fails when git is off PATH\" | :269, :270 | a skip or pass without git | CARRIED |\n| D12 | docstring | \"passes when dist was committed after src ... though older on disk\" | :232 | a crawler test that always fails, or one that only compares mtimes | CARRIED |\n| N1 | name | `test_crawler_dist_under_node_returns_pinned_values` | :160 | a dist with any wrong pinned value | CARRIED |\n| N2 | name | `test_durable_crawler_test_passes_on_this_tree` | :169 | a skipping or missing crawler test | CARRIED |\n| N3 | name | `..._fails_on_current_dist_with_one_wrong_value` | :197, :198 | a crawler test that does not compare values | CARRIED |\n| N4 | name | `..._fails_loudly_without_node` | :205, :206 | a skip, or a failure with no hint | CARRIED |\n| N5 | name | `..._fails_loudly_when_dist_is_missing` | :211, :212 | the same | CARRIED |\n| N6 | name | `..._fails_loudly_when_src_committed_after_dist` | :222, :223 | a check that only compares mtimes | CARRIED |\n| N7 | name | `..._passes_when_dist_committed_after_src_though_older_on_disk` | :232 | a check that always fails or only compares mtimes | CARRIED |\n| N8 | name | `..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist` | :253, :254 | a check that only compares commit times | CARRIED |\n| N9 | name | `..._fails_loudly_when_dist_has_no_history_and_is_older` | :262, :263 | a skip or pass with no history | CARRIED |\n| N10 | name | `..._fails_without_git` | :269 | a skip or pass without git | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:4\n   D4 is withdrawn. The docstring sentence \"whose dist is committed with src but is older on disk\" was removed. The test does not assert anything about the real tree's state. That premise now appears only as a comment at :167. Its behaviour was moved into a controlled repo instead: `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk` (:235\u2013242) carries the new docstring clause \"or at the same time as a clean src, though older on disk\" at :242. The prose was narrowed and a relocated assertion was added. No assertion was added about the real tree.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:173, :235\n   Two tests that the ledger does not name are new this round: `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input` and `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk`. Both of their name clauses are carried: the first at :184\u2013186 with control :180, the second at :242. I found no claim defect in either.\n\nNOT ASSESSED\n1. `code_under_test` tests/active/test_host_normalisation.py, as read, has no `crawler_dist` test and no `SRC`/`DIST` Path constants. So I could not confirm from the code what the `PATHS_PLUGIN` redirection (:56\u201367) targets, or what the durable test's messages will contain. The C1b, C2 and D5\u2013D12 rows were judged from the test's assertions and its junit-outcome harness (:77\u2013102) alone.\n2. engine/crawler/src/host-filters.ts and engine/crawler/dist/host-filters.js were not supplied and did not resolve by Glob. So I could not check the premise at :176 and :192 that `EXPORT_LINE` and `LOWERCASE_LINE` each appear exactly once. The test asserts both itself.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:160\n   assert _dist_outputs(REAL_DIST) == PINNED\n   test_crawler_dist_under_node_returns_pinned_values checks the real dist and the fixture,\n   and the phase writes neither. Its comment says it is already true before the phase (line 158),\n   so it will pass against a stub durable test. The file still blocks a stub because every other\n   test runs the durable test. shape.md has no entry for a premise test inside a checkpoint.\n   It is noted here so that nobody reads this test's green result as evidence the phase is done.\n\nPREDICTED FAILURE\nThe durable file tests/active/test_host_normalisation.py has no test matching `-k crawler_dist`\nyet, so `_run_crawler_test` returns \"not collected\" every time.\n- Line 169 fails on `assert outcome == \"passed\", message`.\n- Lines 184, 197, 205, 211, 222, 232, 242, 253, 262 and 269 fail the same way on their\n  `assert outcome == ...` line, and so does each of the 15 parametrized cases at line 184.\n- test_crawler_dist_under_node_returns_pinned_values (lines 157-163) passes.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The checkpoint uses only pytest's built-in `tmp_path`.\n   I did not read the `conftest.py` that the durable file imports `ROOT` from (line 11). Nothing\n   in the checkpoint depends on it.\n2. I read `code_under_test` in its current form. The durable `crawler_dist` test the checkpoint\n   drives does not exist yet, so the stub question was answered from how the checkpoint's\n   assertions are built. That covers the outcome and message checks paired with the \"must pass\"\n   controls at lines 169, 232 and 242, and the 15-input parametrization at line 172.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (29 clauses: 7 must_prove, 12 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"`dist/host-filters.js` run under node returns\" the expected value for every pinned input | :160 | a dist that gets any one of the 15 inputs wrong or leaves one out. The whole dict is compared, so if `zip` truncates, a key goes missing and equality fails | CARRIED |\n| C1b | must_prove | the crawler test holds dist to \"each fixture pair\" | :184, :185 (control :180) | a crawler test that checks only some of the pairs. The test is parametrised over every fixture input (:172), and each run's dist is wrong on that one input only (:180), so leaving out any pair lets one run pass | CARRIED |\n| C2a | must_prove | \"a missing node\" makes the crawler test fail rather than skip | :205, :206 | a skip, an error, no test collected, or a failure without the build hint when node is off PATH | CARRIED |\n| C2b | must_prove | \"a missing dist\" fails rather than skips | :211, :212 | a skip, error or silent pass when DIST does not exist | CARRIED |\n| C2c1 | must_prove | \"a stale dist\" (src committed after dist) fails | :222, :223 | a check that only compares mtimes, because dist is newer on disk here (:220), and a skip | CARRIED |\n| C2c2 | must_prove | \"a stale dist\" (uncommitted src edit newer on disk) fails | :253, :254 | a check that only compares commit times, because the commit times are equal (:247\u2013248) | CARRIED |\n| C2c3 | must_prove | \"a stale dist\" (dist has no history and is older on disk) fails | :262, :263 | a check that skips or passes when git has no commit time for dist | CARRIED |\n| D1 | docstring | \"imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values\" | :160 | a dist that differs on any pinned input | CARRIED |\n| D2 | docstring | \"so with phase 1 the Python port equals the crawler on the fixture\" | :162, :163 (with :160) | a fixture that differs from PINNED, or holds a duplicated input, so it no longer matches the dist's output. The fixture is now pinned to the same pairs the dist is held to | CARRIED |\n| D3 | docstring | \"passes on this tree\" | :169 | a skipping, erroring or missing crawler test (\"not collected\" \u2260 \"passed\") | CARRIED |\n| D4 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D5 | docstring | \"fails, without the build hint, on a current dist that returns a wrong value for one input\" | :184\u2013186, :197\u2013199 | a crawler test that does not compare dist's output, or that reports it as staleness (:186, :199) | CARRIED |\n| D6 | docstring | fails, never skips, with the build hint \"when node is off PATH\" | :205, :206 | a skip, or a failure without the hint | CARRIED |\n| D7 | docstring | \"... when dist is missing\" | :211, :212 | the same, for a missing dist | CARRIED |\n| D8 | docstring | \"... when src was committed after dist\" | :222, :223 | a check that only compares mtimes | CARRIED |\n| D9 | docstring | \"... when src has an uncommitted edit newer on disk than dist\" | :253, :254 | a check that only compares commit times | CARRIED |\n| D10 | docstring | \"... when dist has no history and is older on disk than src\" | :262, :263 | a skip or pass when dist has no commit history | CARRIED |\n| D11 | docstring | \"it fails when git is off PATH\" | :269, :270 | a skip or pass without git | CARRIED |\n| D12 | docstring | \"passes when dist was committed after src ... though older on disk\" | :232 | a crawler test that always fails, or one that only compares mtimes | CARRIED |\n| N1 | name | `test_crawler_dist_under_node_returns_pinned_values` | :160 | a dist with any wrong pinned value | CARRIED |\n| N2 | name | `test_durable_crawler_test_passes_on_this_tree` | :169 | a skipping or missing crawler test | CARRIED |\n| N3 | name | `..._fails_on_current_dist_with_one_wrong_value` | :197, :198 | a crawler test that does not compare values | CARRIED |\n| N4 | name | `..._fails_loudly_without_node` | :205, :206 | a skip, or a failure with no hint | CARRIED |\n| N5 | name | `..._fails_loudly_when_dist_is_missing` | :211, :212 | the same | CARRIED |\n| N6 | name | `..._fails_loudly_when_src_committed_after_dist` | :222, :223 | a check that only compares mtimes | CARRIED |\n| N7 | name | `..._passes_when_dist_committed_after_src_though_older_on_disk` | :232 | a check that always fails or only compares mtimes | CARRIED |\n| N8 | name | `..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist` | :253, :254 | a check that only compares commit times | CARRIED |\n| N9 | name | `..._fails_loudly_when_dist_has_no_history_and_is_older` | :262, :263 | a skip or pass with no history | CARRIED |\n| N10 | name | `..._fails_without_git` | :269 | a skip or pass without git | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:4\n   D4 is withdrawn. The docstring sentence \"whose dist is committed with src but is older on disk\" was removed. The test does not assert anything about the real tree's state. That premise now appears only as a comment at :167. Its behaviour was moved into a controlled repo instead: `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk` (:235\u2013242) carries the new docstring clause \"or at the same time as a clean src, though older on disk\" at :242. The prose was narrowed and a relocated assertion was added. No assertion was added about the real tree.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase2.py:173, :235\n   Two tests that the ledger does not name are new this round: `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input` and `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk`. Both of their name clauses are carried: the first at :184\u2013186 with control :180, the second at :242. I found no claim defect in either.\n\nNOT ASSESSED\n1. `code_under_test` tests/active/test_host_normalisation.py, as read, has no `crawler_dist` test and no `SRC`/`DIST` Path constants. So I could not confirm from the code what the `PATHS_PLUGIN` redirection (:56\u201367) targets, or what the durable test's messages will contain. The C1b, C2 and D5\u2013D12 rows were judged from the test's assertions and its junit-outcome harness (:77\u2013102) alone.\n2. engine/crawler/src/host-filters.ts and engine/crawler/dist/host-filters.js were not supplied and did not resolve by Glob. So I could not check the premise at :176 and :192 that `EXPORT_LINE` and `LOWERCASE_LINE` each appear exactly once. The test asserts both itself.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"`dist/host-filters.js` run under node returns\" the expected value for every pinned input",
            "assertion": ":160",
            "excludes": "a dist that gets any one of the 15 inputs wrong or leaves one out. The whole dict is compared, so if `zip` truncates, a key goes missing and equality fails",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the crawler test holds dist to \"each fixture pair\"",
            "assertion": ":184, :185 (control :180)",
            "excludes": "a crawler test that checks only some of the pairs. The test is parametrised over every fixture input (:172), and each run's dist is wrong on that one input only (:180), so leaving out any pair lets one run pass",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"a missing node\" makes the crawler test fail rather than skip",
            "assertion": ":205, :206",
            "excludes": "a skip, an error, no test collected, or a failure without the build hint when node is off PATH",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"a missing dist\" fails rather than skips",
            "assertion": ":211, :212",
            "excludes": "a skip, error or silent pass when DIST does not exist",
            "status": "CARRIED"
          },
          {
            "id": "C2c1",
            "source": "must_prove",
            "clause": "\"a stale dist\" (src committed after dist) fails",
            "assertion": ":222, :223",
            "excludes": "a check that only compares mtimes, because dist is newer on disk here (:220), and a skip",
            "status": "CARRIED"
          },
          {
            "id": "C2c2",
            "source": "must_prove",
            "clause": "\"a stale dist\" (uncommitted src edit newer on disk) fails",
            "assertion": ":253, :254",
            "excludes": "a check that only compares commit times, because the commit times are equal (:247\u2013248)",
            "status": "CARRIED"
          },
          {
            "id": "C2c3",
            "source": "must_prove",
            "clause": "\"a stale dist\" (dist has no history and is older on disk) fails",
            "assertion": ":262, :263",
            "excludes": "a check that skips or passes when git has no commit time for dist",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values\"",
            "assertion": ":160",
            "excludes": "a dist that differs on any pinned input",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"so with phase 1 the Python port equals the crawler on the fixture\"",
            "assertion": ":162, :163 (with :160)",
            "excludes": "a fixture that differs from PINNED, or holds a duplicated input, so it no longer matches the dist's output. The fixture is now pinned to the same pairs the dist is held to",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"passes on this tree\"",
            "assertion": ":169",
            "excludes": "a skipping, erroring or missing crawler test (\"not collected\" \u2260 \"passed\")",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"fails, without the build hint, on a current dist that returns a wrong value for one input\"",
            "assertion": ":184\u2013186, :197\u2013199",
            "excludes": "a crawler test that does not compare dist's output, or that reports it as staleness (:186, :199)",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "fails, never skips, with the build hint \"when node is off PATH\"",
            "assertion": ":205, :206",
            "excludes": "a skip, or a failure without the hint",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"... when dist is missing\"",
            "assertion": ":211, :212",
            "excludes": "the same, for a missing dist",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"... when src was committed after dist\"",
            "assertion": ":222, :223",
            "excludes": "a check that only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"... when src has an uncommitted edit newer on disk than dist\"",
            "assertion": ":253, :254",
            "excludes": "a check that only compares commit times",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"... when dist has no history and is older on disk than src\"",
            "assertion": ":262, :263",
            "excludes": "a skip or pass when dist has no commit history",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"it fails when git is off PATH\"",
            "assertion": ":269, :270",
            "excludes": "a skip or pass without git",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"passes when dist was committed after src ... though older on disk\"",
            "assertion": ":232",
            "excludes": "a crawler test that always fails, or one that only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_crawler_dist_under_node_returns_pinned_values`",
            "assertion": ":160",
            "excludes": "a dist with any wrong pinned value",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_durable_crawler_test_passes_on_this_tree`",
            "assertion": ":169",
            "excludes": "a skipping or missing crawler test",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "`..._fails_on_current_dist_with_one_wrong_value`",
            "assertion": ":197, :198",
            "excludes": "a crawler test that does not compare values",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "`..._fails_loudly_without_node`",
            "assertion": ":205, :206",
            "excludes": "a skip, or a failure with no hint",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "`..._fails_loudly_when_dist_is_missing`",
            "assertion": ":211, :212",
            "excludes": "the same",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "`..._fails_loudly_when_src_committed_after_dist`",
            "assertion": ":222, :223",
            "excludes": "a check that only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "`..._passes_when_dist_committed_after_src_though_older_on_disk`",
            "assertion": ":232",
            "excludes": "a check that always fails or only compares mtimes",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "`..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist`",
            "assertion": ":253, :254",
            "excludes": "a check that only compares commit times",
            "status": "CARRIED"
          },
          {
            "id": "N9",
            "source": "name",
            "clause": "`..._fails_loudly_when_dist_has_no_history_and_is_older`",
            "assertion": ":262, :263",
            "excludes": "a skip or pass with no history",
            "status": "CARRIED"
          },
          {
            "id": "N10",
            "source": "name",
            "clause": "`..._fails_without_git`",
            "assertion": ":269",
            "excludes": "a skip or pass without git",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_10_normalise_instance_hosts_phase3.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row fails at line 44 on\n`assert hosts == {\"tube.example\"}` because fetch_hosts returns\n{\"https://tube.example/\", \"tube.example\"}. test_both_fetchers_drop_entries_that_normalise_to_none\nfails at line 58 because fetch_hosts returns {\".\", \"https://\", \"tube.example.\",\n\"https://other.example/videos\"}. test_fetch_hosts_still_raises_when_every_entry_normalises_to_none\nfails at lines 65-66 with \"DID NOT RAISE ValueError\", because \".\" and \"https://\" survive\nthe current strip/lower and leave the host set non-empty.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines its only non-builtin fixture\n   (`jobs`, line 29-31) and otherwise uses pytest's `tmp_path`. No conftest was needed\n   to answer the shape questions, and none was read.\n2. The test imports both job modules with `spec_from_file_location` (lines 22-31).\n   Those imports pull in `scripts.cli_format`, `server_config` and `data.moderation`,\n   which were not read. Whether that import succeeds was not checked, so the predicted\n   failure assumes collection gets past the `jobs` fixture.\n```",
        "claim": "```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 4 must_prove, 8 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example` | :44 | strip-and-lowercase only, which gives {\"https://tube.example/\", \"tube.example\"}. A scheme or trailing slash left in place breaks set equality | CARRIED |\n| C1b | must_prove | \"which `sync_hosts` stores as one row\" | :48, :49 | two rows stored, or a host stored with its scheme. (1,0,1) excludes total=2 or added=2, and the exact row list excludes any row other than `tube.example` | CARRIED |\n| C2a | must_prove | \"Entries that normalise to None are dropped\" | :58, :59 | keeping `.` or `https://`, which strip/lower lets through. Keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these | CARRIED |\n| C2b | must_prove | \"`fetch_join_hosts` returns the same host set as `fetch_hosts`\" | :58, :59 | updater-worker left on its own normaliser. Both fetchers read the same payload and are held to the same literal set, so any difference on this input fails | CARRIED |\n| D1 | docstring | \"normalise hosts-list entries with `normalize_host_token`\" | none | nothing. A hand-rolled normaliser that matches on these six inputs passes. No assertion ties either fetcher's output to `normalize_host_token` | UNCARRIED |\n| D2 | docstring | `fetch_hosts` reads `[\"https://Tube.Example/\", \"tube.example\"]` as the one host `tube.example` | :44 | a set holding two hosts, or holding a URL form | CARRIED |\n| D3 | docstring | `sync_hosts` on a fresh schema in a tmp_path SQLite file \"returns (1, 0, 1)\" | :48 | a wrong total, removed or added count | CARRIED |\n| D4 | docstring | \"leaves exactly the row `tube.example`\" | :49 | any extra row, or a missing row | CARRIED |\n| D5 | docstring | on a `{\"data\": [...]}` payload, `fetch_hosts` drops `\"\"`, `\"   \"`, `\".\"`, `\"https://\"` | :58 | any of the four kept as a host | CARRIED |\n| D6 | docstring | `fetch_join_hosts` in updater-worker.py drops the same entries | :59 | any of the four kept as a host | CARRIED |\n| D7 | docstring | both \"return exactly `{\"tube.example\", \"other.example\"}`\" | :58, :59 | a trailing dot, path, scheme or case left in place | CARRIED |\n| D8 | docstring | `fetch_hosts` on an all-None payload \"still raises ValueError 'Whitelist contained no hosts.'\" | :65 | returning an empty set or a set containing `.`/`https://`, or raising with a different message (anchored regex) | CARRIED |\n| N1 | name | test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: \"collapses url and bare host\" | :44 | two hosts kept | CARRIED |\n| N2 | name | same test: \"into one synced row\" | :48, :49 | more than one row, or a different row | CARRIED |\n| N3 | name | test_both_fetchers_drop_entries_that_normalise_to_none | :58, :59 | either fetcher keeping a None-normalising entry | CARRIED |\n| N4 | name | test_fetch_hosts_still_raises_when_every_entry_normalises_to_none | :65 | no raise on an all-None payload | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:1\n   D1 is UNCARRIED. The docstring says both jobs normalise \"with `normalize_host_token`\",\n   but every assertion compares against a literal set built from six hand-picked inputs.\n   Nothing excludes a local normaliser that agrees on those six and diverges elsewhere.\n   One fix is to add an assertion that runs every `input` from `tests/active/host_tokens.json`\n   through both fetchers and compares the result with the non-None `normalize_host_token`\n   outputs. The other is to narrow the docstring sentence. D1 is not in `must_prove`, so this\n   does not block.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:62\n   The failure mode is tested only for `fetch_hosts`. `fetch_join_hosts` has no test for a\n   payload where every entry normalises to None, so its expected behaviour there (unlike\n   `fetch_hosts` it has no empty-set raise) is not established.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:19\n   `DROPPED` covers empty, whitespace-only, a lone dot and a bare scheme. Nothing covers\n   non-string edges the fetchers accept: a `{\"data\": [...]}` entry whose `host` is null or\n   missing, or a non-string list entry. C2b (\"same host set\") is also checked on the dict\n   payload only. The list-shaped payload from :42 never goes through `fetch_join_hosts`.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and its\n   own module-scoped `jobs` fixture (:29\u201331), so no conftest was needed for independence.\n   The `conftest.py` that `tests/active/test_host_normalisation.py` imports `ROOT` from was\n   not read.\n2. `data.moderation.normalize_host_token`, which the docstring (D1) and `must_prove` C2\n   (\"normalise to None\") refer to, was not in `code_under_test` and was not read. Whether\n   the four `DROPPED` entries really do normalise to None was taken from the test's own\n   premise and was not checked against that function.\n```",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row fails at line 44 on\n`assert hosts == {\"tube.example\"}` because fetch_hosts returns\n{\"https://tube.example/\", \"tube.example\"}. test_both_fetchers_drop_entries_that_normalise_to_none\nfails at line 58 because fetch_hosts returns {\".\", \"https://\", \"tube.example.\",\n\"https://other.example/videos\"}. test_fetch_hosts_still_raises_when_every_entry_normalises_to_none\nfails at lines 65-66 with \"DID NOT RAISE ValueError\", because \".\" and \"https://\" survive\nthe current strip/lower and leave the host set non-empty.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines its only non-builtin fixture\n   (`jobs`, line 29-31) and otherwise uses pytest's `tmp_path`. No conftest was needed\n   to answer the shape questions, and none was read.\n2. The test imports both job modules with `spec_from_file_location` (lines 22-31).\n   Those imports pull in `scripts.cli_format`, `server_config` and `data.moderation`,\n   which were not read. Whether that import succeeds was not checked, so the predicted\n   failure assumes collection gets past the `jobs` fixture.\n```\n\n### devsecops-test-claim-auditor\n\n```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 4 must_prove, 8 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example` | :44 | strip-and-lowercase only, which gives {\"https://tube.example/\", \"tube.example\"}. A scheme or trailing slash left in place breaks set equality | CARRIED |\n| C1b | must_prove | \"which `sync_hosts` stores as one row\" | :48, :49 | two rows stored, or a host stored with its scheme. (1,0,1) excludes total=2 or added=2, and the exact row list excludes any row other than `tube.example` | CARRIED |\n| C2a | must_prove | \"Entries that normalise to None are dropped\" | :58, :59 | keeping `.` or `https://`, which strip/lower lets through. Keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these | CARRIED |\n| C2b | must_prove | \"`fetch_join_hosts` returns the same host set as `fetch_hosts`\" | :58, :59 | updater-worker left on its own normaliser. Both fetchers read the same payload and are held to the same literal set, so any difference on this input fails | CARRIED |\n| D1 | docstring | \"normalise hosts-list entries with `normalize_host_token`\" | none | nothing. A hand-rolled normaliser that matches on these six inputs passes. No assertion ties either fetcher's output to `normalize_host_token` | UNCARRIED |\n| D2 | docstring | `fetch_hosts` reads `[\"https://Tube.Example/\", \"tube.example\"]` as the one host `tube.example` | :44 | a set holding two hosts, or holding a URL form | CARRIED |\n| D3 | docstring | `sync_hosts` on a fresh schema in a tmp_path SQLite file \"returns (1, 0, 1)\" | :48 | a wrong total, removed or added count | CARRIED |\n| D4 | docstring | \"leaves exactly the row `tube.example`\" | :49 | any extra row, or a missing row | CARRIED |\n| D5 | docstring | on a `{\"data\": [...]}` payload, `fetch_hosts` drops `\"\"`, `\"   \"`, `\".\"`, `\"https://\"` | :58 | any of the four kept as a host | CARRIED |\n| D6 | docstring | `fetch_join_hosts` in updater-worker.py drops the same entries | :59 | any of the four kept as a host | CARRIED |\n| D7 | docstring | both \"return exactly `{\"tube.example\", \"other.example\"}`\" | :58, :59 | a trailing dot, path, scheme or case left in place | CARRIED |\n| D8 | docstring | `fetch_hosts` on an all-None payload \"still raises ValueError 'Whitelist contained no hosts.'\" | :65 | returning an empty set or a set containing `.`/`https://`, or raising with a different message (anchored regex) | CARRIED |\n| N1 | name | test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: \"collapses url and bare host\" | :44 | two hosts kept | CARRIED |\n| N2 | name | same test: \"into one synced row\" | :48, :49 | more than one row, or a different row | CARRIED |\n| N3 | name | test_both_fetchers_drop_entries_that_normalise_to_none | :58, :59 | either fetcher keeping a None-normalising entry | CARRIED |\n| N4 | name | test_fetch_hosts_still_raises_when_every_entry_normalises_to_none | :65 | no raise on an all-None payload | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:1\n   D1 is UNCARRIED. The docstring says both jobs normalise \"with `normalize_host_token`\",\n   but every assertion compares against a literal set built from six hand-picked inputs.\n   Nothing excludes a local normaliser that agrees on those six and diverges elsewhere.\n   One fix is to add an assertion that runs every `input` from `tests/active/host_tokens.json`\n   through both fetchers and compares the result with the non-None `normalize_host_token`\n   outputs. The other is to narrow the docstring sentence. D1 is not in `must_prove`, so this\n   does not block.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:62\n   The failure mode is tested only for `fetch_hosts`. `fetch_join_hosts` has no test for a\n   payload where every entry normalises to None, so its expected behaviour there (unlike\n   `fetch_hosts` it has no empty-set raise) is not established.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:19\n   `DROPPED` covers empty, whitespace-only, a lone dot and a bare scheme. Nothing covers\n   non-string edges the fetchers accept: a `{\"data\": [...]}` entry whose `host` is null or\n   missing, or a non-string list entry. C2b (\"same host set\") is also checked on the dict\n   payload only. The list-shaped payload from :42 never goes through `fetch_join_hosts`.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and its\n   own module-scoped `jobs` fixture (:29\u201331), so no conftest was needed for independence.\n   The `conftest.py` that `tests/active/test_host_normalisation.py` imports `ROOT` from was\n   not read.\n2. `data.moderation.normalize_host_token`, which the docstring (D1) and `must_prove` C2\n   (\"normalise to None\") refer to, was not in `code_under_test` and was not read. Whether\n   the four `DROPPED` entries really do normalise to None was taken from the test's own\n   premise and was not checked against that function.\n```",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`",
            "assertion": ":44",
            "excludes": "strip-and-lowercase only, which gives {\"https://tube.example/\", \"tube.example\"}. A scheme or trailing slash left in place breaks set equality",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"which `sync_hosts` stores as one row\"",
            "assertion": ":48, :49",
            "excludes": "two rows stored, or a host stored with its scheme. (1,0,1) excludes total=2 or added=2, and the exact row list excludes any row other than `tube.example`",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"Entries that normalise to None are dropped\"",
            "assertion": ":58, :59",
            "excludes": "keeping `.` or `https://`, which strip/lower lets through. Keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"`fetch_join_hosts` returns the same host set as `fetch_hosts`\"",
            "assertion": ":58, :59",
            "excludes": "updater-worker left on its own normaliser. Both fetchers read the same payload and are held to the same literal set, so any difference on this input fails",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"normalise hosts-list entries with `normalize_host_token`\"",
            "assertion": "none",
            "excludes": "nothing. A hand-rolled normaliser that matches on these six inputs passes. No assertion ties either fetcher's output to `normalize_host_token`",
            "status": "UNCARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "`fetch_hosts` reads `[\"https://Tube.Example/\", \"tube.example\"]` as the one host `tube.example`",
            "assertion": ":44",
            "excludes": "a set holding two hosts, or holding a URL form",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "`sync_hosts` on a fresh schema in a tmp_path SQLite file \"returns (1, 0, 1)\"",
            "assertion": ":48",
            "excludes": "a wrong total, removed or added count",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"leaves exactly the row `tube.example`\"",
            "assertion": ":49",
            "excludes": "any extra row, or a missing row",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "on a `{\"data\": [...]}` payload, `fetch_hosts` drops `\"\"`, `\"   \"`, `\".\"`, `\"https://\"`",
            "assertion": ":58",
            "excludes": "any of the four kept as a host",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "`fetch_join_hosts` in updater-worker.py drops the same entries",
            "assertion": ":59",
            "excludes": "any of the four kept as a host",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "both \"return exactly `{\"tube.example\", \"other.example\"}`\"",
            "assertion": ":58, :59",
            "excludes": "a trailing dot, path, scheme or case left in place",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "`fetch_hosts` on an all-None payload \"still raises ValueError 'Whitelist contained no hosts.'\"",
            "assertion": ":65",
            "excludes": "returning an empty set or a set containing `.`/`https://`, or raising with a different message (anchored regex)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: \"collapses url and bare host\"",
            "assertion": ":44",
            "excludes": "two hosts kept",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "same test: \"into one synced row\"",
            "assertion": ":48, :49",
            "excludes": "more than one row, or a different row",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test_both_fetchers_drop_entries_that_normalise_to_none",
            "assertion": ":58, :59",
            "excludes": "either fetcher keeping a None-normalising entry",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test_fetch_hosts_still_raises_when_every_entry_normalises_to_none",
            "assertion": ":65",
            "excludes": "no raise on an all-None payload",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails first at line 44 on `assert hosts == {\"tube.example\"}`, because `fetch_hosts`\nstill only strips and lowercases each entry, so it returns\n{\"https://tube.example/\", \"tube.example\"}. Line 58 fails the same way: the set still holds\n\".\", \"https://\", \"tube.example.\" and \"https://other.example/videos\". Line 65 fails with\n\"DID NOT RAISE\", because \".\" and \"https://\" pass the `if host_value:` check at\nsync-whitelist.py:244, so the set is not empty and no ValueError is raised.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines its own fixtures and helpers\n   (`jobs`, `_serve`, `_load`, lines 22\u201337) and uses no conftest fixture, so nothing was\n   left unread.\n2. `code_under_test` is labelled EDITED, but sync-whitelist.py:219\u2013250 and\n   updater-worker.py:414\u2013441 contain no normalisation call. The prediction is made against\n   those files as they read now.\n3. tests/active/test_host_normalisation.py is listed in `code_under_test`. The test under\n   audit does not import or exercise it, so no finding was drawn from it.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 4 must_prove, 8 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example` | :44 | Strip-and-lowercase only, which gives {\"https://tube.example/\", \"tube.example\"}. A scheme or trailing slash left in place fails the exact set equality | CARRIED |\n| C1b | must_prove | \"which `sync_hosts` stores as one row\" | :48, :49 | Two rows stored, or a host stored with its scheme. (1, 0, 1) excludes total=2 and added=2, and the exact row list excludes any row other than `tube.example` | CARRIED |\n| C2a | must_prove | \"Entries that normalise to None are dropped\" | :58, :59 | Keeping `.` or `https://`, which strip/lower lets through, or keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these | CARRIED |\n| C2b | must_prove | \"`fetch_join_hosts` returns the same host set as `fetch_hosts`\" | :58, :59 | updater-worker left on its own normaliser. Both fetchers read one payload and are held to the same literal set, so any difference on this input fails | CARRIED |\n| D1 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D2 | docstring | `fetch_hosts` reads `[\"https://Tube.Example/\", \"tube.example\"]` as the one host `tube.example` | :44 | A set holding two hosts, or holding a URL form | CARRIED |\n| D3 | docstring | `sync_hosts` on a fresh schema in a tmp_path SQLite file \"returns (1, 0, 1)\" | :48 | A wrong total, removed or added count | CARRIED |\n| D4 | docstring | \"leaves exactly the row `tube.example`\" | :49 | Any extra row, or a missing row | CARRIED |\n| D5 | docstring | on a `{\"data\": [...]}` payload, `fetch_hosts` drops `\"\"`, `\"   \"`, `\".\"`, `\"https://\"` | :58 | Any of the four kept as a host | CARRIED |\n| D6 | docstring | `fetch_join_hosts` in updater-worker.py drops the same entries | :59 | Any of the four kept as a host | CARRIED |\n| D7 | docstring | both \"return exactly `{\"tube.example\", \"other.example\"}`\" | :58, :59 | A trailing dot, path, scheme or case left in place | CARRIED |\n| D8 | docstring | `fetch_hosts` on an all-None payload \"still raises ValueError 'Whitelist contained no hosts.'\" | :65 | Returning an empty set or a set containing `.`/`https://`, or raising with a different message (the regex is anchored) | CARRIED |\n| N1 | name | test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: \"collapses url and bare host\" | :44 | Two hosts kept | CARRIED |\n| N2 | name | same test: \"into one synced row\" | :48, :49 | More than one row, or a different row | CARRIED |\n| N3 | name | test_both_fetchers_drop_entries_that_normalise_to_none | :58, :59 | Either fetcher keeping an entry that normalises to None | CARRIED |\n| N4 | name | test_fetch_hosts_still_raises_when_every_entry_normalises_to_none | :65 | No raise on an all-None payload | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:1\n   D1 was UNCARRIED on the first audit. It clears this round because the prose was narrowed, not because an assertion was added. The docstring's opening sentence used to claim the jobs normalise \"with `normalize_host_token`\". It now reads \"normalise hosts-list entries to bare lowercase hosts, as pinned by the literal inputs below\", and the six literal inputs carry that narrower sentence. Nothing in the test ties either fetcher's output to `normalize_host_token`, or to the pinned pairs in `tests/active/host_tokens.json`. A hand-rolled normaliser that agrees on these six inputs still passes. The build should know this reuse is no longer claimed or checked here.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines its own fixture (`jobs`, :29-31) and uses only pytest's built-in `tmp_path`, so it needs no conftest. `tests/active/test_host_normalisation.py` imports `ROOT` from a `conftest` that was not read, because that file is listed as code under test and is not the test under audit.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails first at line 44 on `assert hosts == {\"tube.example\"}`, because `fetch_hosts`\nstill only strips and lowercases each entry, so it returns\n{\"https://tube.example/\", \"tube.example\"}. Line 58 fails the same way: the set still holds\n\".\", \"https://\", \"tube.example.\" and \"https://other.example/videos\". Line 65 fails with\n\"DID NOT RAISE\", because \".\" and \"https://\" pass the `if host_value:` check at\nsync-whitelist.py:244, so the set is not empty and no ValueError is raised.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines its own fixtures and helpers\n   (`jobs`, `_serve`, `_load`, lines 22\u201337) and uses no conftest fixture, so nothing was\n   left unread.\n2. `code_under_test` is labelled EDITED, but sync-whitelist.py:219\u2013250 and\n   updater-worker.py:414\u2013441 contain no normalisation call. The prediction is made against\n   those files as they read now.\n3. tests/active/test_host_normalisation.py is listed in `code_under_test`. The test under\n   audit does not import or exercise it, so no finding was drawn from it.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 4 must_prove, 8 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example` | :44 | Strip-and-lowercase only, which gives {\"https://tube.example/\", \"tube.example\"}. A scheme or trailing slash left in place fails the exact set equality | CARRIED |\n| C1b | must_prove | \"which `sync_hosts` stores as one row\" | :48, :49 | Two rows stored, or a host stored with its scheme. (1, 0, 1) excludes total=2 and added=2, and the exact row list excludes any row other than `tube.example` | CARRIED |\n| C2a | must_prove | \"Entries that normalise to None are dropped\" | :58, :59 | Keeping `.` or `https://`, which strip/lower lets through, or keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these | CARRIED |\n| C2b | must_prove | \"`fetch_join_hosts` returns the same host set as `fetch_hosts`\" | :58, :59 | updater-worker left on its own normaliser. Both fetchers read one payload and are held to the same literal set, so any difference on this input fails | CARRIED |\n| D1 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D2 | docstring | `fetch_hosts` reads `[\"https://Tube.Example/\", \"tube.example\"]` as the one host `tube.example` | :44 | A set holding two hosts, or holding a URL form | CARRIED |\n| D3 | docstring | `sync_hosts` on a fresh schema in a tmp_path SQLite file \"returns (1, 0, 1)\" | :48 | A wrong total, removed or added count | CARRIED |\n| D4 | docstring | \"leaves exactly the row `tube.example`\" | :49 | Any extra row, or a missing row | CARRIED |\n| D5 | docstring | on a `{\"data\": [...]}` payload, `fetch_hosts` drops `\"\"`, `\"   \"`, `\".\"`, `\"https://\"` | :58 | Any of the four kept as a host | CARRIED |\n| D6 | docstring | `fetch_join_hosts` in updater-worker.py drops the same entries | :59 | Any of the four kept as a host | CARRIED |\n| D7 | docstring | both \"return exactly `{\"tube.example\", \"other.example\"}`\" | :58, :59 | A trailing dot, path, scheme or case left in place | CARRIED |\n| D8 | docstring | `fetch_hosts` on an all-None payload \"still raises ValueError 'Whitelist contained no hosts.'\" | :65 | Returning an empty set or a set containing `.`/`https://`, or raising with a different message (the regex is anchored) | CARRIED |\n| N1 | name | test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: \"collapses url and bare host\" | :44 | Two hosts kept | CARRIED |\n| N2 | name | same test: \"into one synced row\" | :48, :49 | More than one row, or a different row | CARRIED |\n| N3 | name | test_both_fetchers_drop_entries_that_normalise_to_none | :58, :59 | Either fetcher keeping an entry that normalises to None | CARRIED |\n| N4 | name | test_fetch_hosts_still_raises_when_every_entry_normalises_to_none | :65 | No raise on an all-None payload | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_normalise_instance_hosts_phase3.py:1\n   D1 was UNCARRIED on the first audit. It clears this round because the prose was narrowed, not because an assertion was added. The docstring's opening sentence used to claim the jobs normalise \"with `normalize_host_token`\". It now reads \"normalise hosts-list entries to bare lowercase hosts, as pinned by the literal inputs below\", and the six literal inputs carry that narrower sentence. Nothing in the test ties either fetcher's output to `normalize_host_token`, or to the pinned pairs in `tests/active/host_tokens.json`. A hand-rolled normaliser that agrees on these six inputs still passes. The build should know this reuse is no longer claimed or checked here.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines its own fixture (`jobs`, :29-31) and uses only pytest's built-in `tmp_path`, so it needs no conftest. `tests/active/test_host_normalisation.py` imports `ROOT` from a `conftest` that was not read, because that file is listed as code under test and is not the test under audit.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`",
            "assertion": ":44",
            "excludes": "Strip-and-lowercase only, which gives {\"https://tube.example/\", \"tube.example\"}. A scheme or trailing slash left in place fails the exact set equality",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"which `sync_hosts` stores as one row\"",
            "assertion": ":48, :49",
            "excludes": "Two rows stored, or a host stored with its scheme. (1, 0, 1) excludes total=2 and added=2, and the exact row list excludes any row other than `tube.example`",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"Entries that normalise to None are dropped\"",
            "assertion": ":58, :59",
            "excludes": "Keeping `.` or `https://`, which strip/lower lets through, or keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"`fetch_join_hosts` returns the same host set as `fetch_hosts`\"",
            "assertion": ":58, :59",
            "excludes": "updater-worker left on its own normaliser. Both fetchers read one payload and are held to the same literal set, so any difference on this input fails",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "`fetch_hosts` reads `[\"https://Tube.Example/\", \"tube.example\"]` as the one host `tube.example`",
            "assertion": ":44",
            "excludes": "A set holding two hosts, or holding a URL form",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "`sync_hosts` on a fresh schema in a tmp_path SQLite file \"returns (1, 0, 1)\"",
            "assertion": ":48",
            "excludes": "A wrong total, removed or added count",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"leaves exactly the row `tube.example`\"",
            "assertion": ":49",
            "excludes": "Any extra row, or a missing row",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "on a `{\"data\": [...]}` payload, `fetch_hosts` drops `\"\"`, `\"   \"`, `\".\"`, `\"https://\"`",
            "assertion": ":58",
            "excludes": "Any of the four kept as a host",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "`fetch_join_hosts` in updater-worker.py drops the same entries",
            "assertion": ":59",
            "excludes": "Any of the four kept as a host",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "both \"return exactly `{\"tube.example\", \"other.example\"}`\"",
            "assertion": ":58, :59",
            "excludes": "A trailing dot, path, scheme or case left in place",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "`fetch_hosts` on an all-None payload \"still raises ValueError 'Whitelist contained no hosts.'\"",
            "assertion": ":65",
            "excludes": "Returning an empty set or a set containing `.`/`https://`, or raising with a different message (the regex is anchored)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: \"collapses url and bare host\"",
            "assertion": ":44",
            "excludes": "Two hosts kept",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "same test: \"into one synced row\"",
            "assertion": ":48, :49",
            "excludes": "More than one row, or a different row",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test_both_fetchers_drop_entries_that_normalise_to_none",
            "assertion": ":58, :59",
            "excludes": "Either fetcher keeping an entry that normalises to None",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test_fetch_hosts_still_raises_when_every_entry_normalises_to_none",
            "assertion": ":65",
            "excludes": "No raise on an all-None payload",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone. The worktree matches the inlined code, and the only duplication left is older than this build and was not added by it (see left_out).\n</refactors>\n\n<left_out>\n1. Shared entry loop. `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py` and `fetch_join_hosts` in `engine/server/db/jobs/updater-worker.py` have the same payload-shape and entry-normalising loop. Moving it into one helper in `data.moderation` would guarantee C2 (both jobs return the same host set) by construction. I did not do it: the two copies existed before this build, the helper would be a new public function in `moderation.py`, and the two jobs still differ in User-Agent, fetch error text and the \"no hosts\" raise. The gating test already pins that they agree.\n2. `if not host: continue` guard in both loops. It is not redundant and stays: `str(None)` is `\"none\"`, and `normalize_host_token` would keep that as a host.\n3. Return annotation on `sync_hosts`. In sync-whitelist.py it says `tuple[int, int]` but the function returns three values. Fixing it would make the comment \"despite its two-element annotation\" in the gated `test_sync_job_stores_one_spelling_per_host` false, and I cannot edit that test. It is also older than this build.\n4. Probe files. `tests/tmp/` still holds files from earlier turns that I have no tool to delete: probe_host_token.py, probe_git_outside_worktree.py, probe_durable_host.py, probe_phase2_env.py, probe_phase2_harness.py, probe_phase3.py, probe_phase3_seams.py and the test_10_normalise_instance_hosts_phase{1,2,3}.py checkpoint copies. The operator should remove the probes.\n5. Pass criteria. The step's \"What the pass is measured against\" section arrived as the unfilled placeholder `{rat_tail_rules}`, so I checked the pass against the role's rules instead. The one `rat-tail:` comment, in `_whatwg_hostname`, names both its limit and its upgrade path.\n6. Checks still owed from phase 3. test-moderation-integration.py, test-orchestrator-smoke.py and the full validate_tests.py baseline comparison have not been run.\n</left_out>\n\n<needs_fresh_red>\n`engine/server/db/jobs/compare-join-hosts.py:80` also reads the JoinPeerTube hosts list, and it still uses `str(host).strip().lower()`. So it can disagree with the two jobs this build changed, for example by counting `https://Tube.Example/` as its own host. Switching it to `normalize_host_token` changes its output, so it is new behaviour, not a refactor. It needs its own phase and red, and it is outside the files this build approved.\n</needs_fresh_red>\n\n<observation>\nThe worktree matches the inlined code, and `normalize_host_token` has exactly two callers, `fetch_hosts` and `fetch_join_hosts`. No refactor was needed without changing either behaviour or code older than this build.\n</observation>"
}
```
dev-flow:state -->

## Entries from earlier runs of this build

## 2026-09-26 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
unchanged since 2026-09-26T18:40:26-04:00 — every fingerprint still holds
  68 passed (45.7s)
```

## 2026-09-26 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### What is being built

Issue `docs/project/issues/06-normalise-instance-hosts.md` (plan `docs/project/plans/10-normalise-instance-hosts.md`, security hardening batch wave 1), category bug. The work is an exact Python port of the crawler's `normalizeHostToken` (`engine/crawler/src/host-filters.ts`, the exported function near line 83). The two Python readers of the JoinPeerTube hosts list will use it: `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py` (function at about line 219, the `str(host).strip().lower()` at about line 243) and `fetch_join_hosts` in `engine/server/db/jobs/updater-worker.py` (function at about line 414, the `strip().lower()` at about line 438). Once earlier waves merge, line numbers will drift, so find these by function name.

### Purpose

Three components read the same JoinPeerTube hosts list: `sync-whitelist.py`, `updater-worker.fetch_join_hosts`, and the TypeScript crawler. Only the crawler normalises. As a result one entry can be stored under two spellings, and the updater gets new/stale host sets wrong and misses denylist matches. After this build, both Python jobs produce the same string as the crawler for the same entry. That closes audit finding SI4-M1 (task 86) as far as the triage decision allows: an exact port, with no validation beyond what `normalizeHostToken` does.

### The helper

- `normalize_host_token(value: str) -> str | None`, with a docstring, in a module of the Engine's shared `engine/server/data` package. Both jobs already put `engine/server` on `sys.path` and import `data.moderation`. Whether it goes in a new module or an existing one is a design decision for the next step. Fewest files is preferred. It must not change `data.moderation.normalize_host`.
- It returns exactly what `normalizeHostToken` returns for the same input:
  1. `value.strip().lower()`. If that is empty, return None.
  2. If it starts with `http://` or `https://`, parse it as a URL and return the hostname, lowercased. Return None if the hostname is empty or parsing fails.
  3. Else, if it contains `/`, parse `https://` + value and return the hostname, lowercased. Return None if the hostname is empty or parsing fails.
  4. Else, return the value with every leading and trailing `.` removed, or None if nothing is left. No URL parse happens in this branch, so ports, `@`, `?`, `#` and non-ASCII characters are kept as they are.
- In branches 2 and 3 the Python parser (stdlib `urllib.parse`, no new dependency) must match the WHATWG `URL.hostname`:
  - userinfo is dropped (`user@host` → `host`)
  - the port is dropped
  - IPv6 literals keep their brackets: `urlparse(...).hostname` returns `::1` and the crawler returns `[::1]`
  - internationalised names are returned as punycode (`bücher.example` → `xn--bcher-kva.example`)
  - input WHATWG rejects returns None
- Branch 4 does no punycode conversion, matching the crawler.

### Pinned expected values

These inputs go into one JSON fixture of input → expected pairs that both the Python and the Node side read. Expected values are the WHATWG results; the Node check confirms them against the crawler's real output:
- `" Tube.Example "` → `"tube.example"`
- `"tube.example."` → `"tube.example"`
- `"..tube.example.."` → `"tube.example"`
- `"https://Tube.Example/"` → `"tube.example"`
- `"http://tube.example:8080/path"` → `"tube.example"`
- `"https://user@tube.example"` → `"tube.example"`
- `"tube.example/videos"` → `"tube.example"`
- `"tube.example:9000"` → `"tube.example:9000"` (branch 4, the port is kept)
- `"https://[::1]:8080/"` → `"[::1]"`
- `"https://bücher.example/"` → `"xn--bcher-kva.example"`
- `""` → null
- `"   "` → null
- `"."` → null
- `"https://"` → null (WHATWG throws; the crawler returns null)

The fixture may grow; every input in it must pass on both sides.

### Job changes

- `fetch_hosts` (sync-whitelist) and `fetch_join_hosts` (updater) each replace `str(host).strip().lower()` with `normalize_host_token(str(host))` and skip entries that return None. Nothing else changes in either function: the fetch, the payload shape handling (`{"data": [...]}` or a list, with `host` taken from dicts), the User-Agent strings, the error types and messages.
- `fetch_hosts` still raises `ValueError("Whitelist contained no hosts.")` when no entry survives. That is existing behaviour. "The job still completes" means a payload in which some entries return None.
- `list_prod_hosts`, `load_denied_hosts`, `compare-join-hosts.py`, `data.moderation.normalize_host`, the denylist/moderation CLIs and all crawler code stay unchanged.

### Acceptance criteria

- A table-driven Python test asserts `normalize_host_token` against every fixture pair.
- The same test runs Node on the crawler's compiled `engine/crawler/dist/host-filters.js`, calling its exported `normalizeHostToken` over the same fixture inputs, and asserts that its output equals the fixture's expected value, and so equals the Python output. `dist/host-filters.js` is present in this worktree and its `normalizeHostToken` matches `src/host-filters.ts`.
  - If `node` is missing, or `dist` is missing or older than `src/host-filters.ts`, the test must fail loudly, never skip, or it builds first. The build checkpoint chooses which.
  - `engine/crawler/node_modules` (and so `tsc`) is not guaranteed in a fresh worktree, so the fail-loudly option does not depend on it.
- Given a hosts payload containing `"https://Tube.Example/"` and `"tube.example"`, the whitelist sync job's host fetch returns the single host `tube.example`, which the job then stores through `sync_hosts`. The payload can be served from a local stdlib HTTP server or a `file://` URL, as `test-orchestrator-smoke.py` already serves `whitelist.json`.
- Entries for which the helper returns None (for example `""`, `"."`, `"https://"`) are not in either job's host set, and the fetch completes as long as at least one entry survives.
- `fetch_join_hosts` returns, for the same payload, the same set as `fetch_hosts`.
- The existing standalone scripts `engine/server/db/jobs/tests/test-moderation-integration.py` and `engine/server/db/jobs/tests/test-orchestrator-smoke.py` still pass. They are not part of `validate_tests.py`'s `tests/active` suite and are run separately.
- The `tests/active` suite still passes through `validate_tests.py`.

### Tests: placement and running

- The new test is a pytest file in `tests/active` (the active tree; the working tree is `tests/tmp`, the archive `tests/archive`). Its JSON fixture sits beside it or in another path both sides can read. The job scripts have hyphenated filenames, so the test loads them with `importlib` (spec from file location), as they cannot be imported normally.
- The new test needs no Engine, so the Engine rate-limit rule, which says Engine-backed files run in their own `validate_tests.py` invocations, does not apply to it. It still applies to the Engine-backed files already in `tests/active`.
- Run `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts`, the `project_dir` in this worktree's `.un/skills/devsecops/config.json`. The record is `tests/last_test_validation.json` and the output `tests/last_test_output.txt`.
- Adding a `test_groups` entry mapping the new test file to the helper module and the two job files happens at harvest on main, not in this worktree.

### Baseline suite state

Before the build the suite ran green: exit code 0, variant false. Any red after the build was introduced by the build.

### Style and constraints

- New code follows the file it lands in:
  - `"""Handle ..."""`-style or descriptive one-line docstrings
  - `from __future__ import annotations` where the module already uses it
  - module-level named constants
  - stdlib only
  - one statement or comment per line, no softwrapping
- No new dependency. No interface with only one implementation.
- Backwards compatibility is not required beyond what is stated here.

### Out of scope

- Changing `normalizeHostToken` or any crawler behaviour.
- Any validation stricter than `normalizeHostToken`: IP literals, ports, userinfo, characters.
- Rewriting host rows already stored in `instances`.
- `data.moderation.normalize_host` and the denylist/moderation CLIs.
- `compare-join-hosts.py`.
- The orchestrator smoke test's own `strip().lower()` host reader.

### Known limitations, accepted

- An entry with no scheme and no `/` goes through branch 4 and is stored almost as given. So `evil@tube.example`, `host?x`, `host#y` and `tube.example:9000` are stored with those characters. The audit's `/ ? # @` concern is closed only for entries that go through the URL branches. This follows from the settled exact-port decision; the operator accepted it.
- `urllib.parse`/`idna` and WHATWG may still differ on inputs outside the fixture:
  - percent-encoding and backslashes
  - IDNA 2003 (Python's `idna` codec) versus UTS #46 (WHATWG), for example `ß`
  - JS `trim()` versus Python `strip()` on characters such as U+FEFF and U+001C-U+001F
  - `toLowerCase()` versus `lower()` on characters such as `İ`
  - Only the fixture inputs are pinned. The upgrade path is to add inputs to the fixture; the Node check then shows any mismatch.
- `data.moderation.normalize_host`, used for denylist input, returns IPv6 without brackets and does not convert to punycode. A denylist entry for an IDN or IPv6 host may therefore not match the new spelling. This is out of scope.
- Hosts already stored under the old spelling are not rewritten, so one updater run after the change may treat the old and new spellings as different hosts.
- The Python test depends on Node and on the crawler's compiled `dist` being present and current.

### Batch and worktree context

- Wave 1 of the security hardening batch (`.scratch/security-hardening-batch/notes.md`), in worktree `.worktrees/fix-10-normalise-instance-hosts`. The build touches no file another batch issue touches: 05 and 02 edit `engine/server/data/interaction_events.py`, `similar.py` and others, not the files above.
- `whitelist.db` is symlinked to the main tree and shared with other lanes. The new test does not touch it.
- When merging, the tracked `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
- Harvest happens on main after the merge.

### conflicts

Purpose ("close the security-audit finding" SI4-M1, which cites entries containing `/ ? # @` reaching URL construction verbatim) vs the settled triage decision "exact port, no extra validation": in branch 4 of `normalizeHostToken` (engine/crawler/src/host-filters.ts), an entry with no scheme and no `/` (e.g. `evil@tube.example`, `host?x`) is only trimmed, lowercased and stripped of dots, so the finding is closed only for entries that go through the URL branches. The operator accepted this as a known limitation.

## 2026-09-26 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

**Where the helper goes.** `normalize_host_token` goes into the existing `engine/server/data/moderation.py`, placed directly after `normalize_host`. That module is already the shared place for host normalisation (its header comment lists it). Both jobs already import from it: `sync-whitelist.py` has a single-line `from data.moderation import ...` and `updater-worker.py` has a parenthesised import. It already imports `urlparse` and uses `from __future__ import annotations`. So the port needs no new file, and each job only adds one name to an import it already has. The new function's docstring follows the file's descriptive one-line style. It must state that the function is an exact port of the crawler's `normalizeHostToken` and differs from `normalize_host` (which is left untouched), so a later reader does not merge the two. Any constants go at module level.

**How the helper works.** It follows the four branches of `normalizeHostToken` (`engine/crawler/src/host-filters.ts:83`) in the same order:
1. Strip and lowercase the input. If the result is empty, return None.
2. If it starts with `http://` or `https://`, parse it as a URL and derive the WHATWG-style hostname.
3. Else, if it contains `/`, parse `https://` + value and derive the hostname the same way.
4. Else, return the value with leading and trailing dots stripped, or None if nothing is left.

Branch 4 never calls the parser. That keeps `tube.example:9000` as it is and does no punycode conversion, as the crawler does.

**Deriving the hostname in branches 2 and 3.** One private step turns `urllib.parse.urlparse` output into the value WHATWG `URL.hostname` would give:
- **Userinfo and port.** `.hostname` already drops userinfo and the port and lowercases the host.
- **Port validity.** The step also reads `.port`. Python raises ValueError on a port that is non-numeric or above 65535, which is input WHATWG also rejects. This costs one attribute read.
- **Empty host.** If the host is missing (`https://`), return None, as the crawler does when `new URL` throws.
- **IPv6 literals.** `.hostname` returns `::1` without brackets. When the host contains `:`, pass it through stdlib `ipaddress.IPv6Address`. That validates it (invalid gives None, like a WHATWG throw) and gives the compressed form WHATWG serialises. Then put the brackets back, giving `[::1]`. Unbalanced brackets make `urlparse` itself raise ValueError, which becomes None.
- **Internationalised names.** If the host is not ASCII, encode it with the stdlib `idna` codec to get punycode (`xn--bcher-kva.example`). A UnicodeError becomes None. ASCII hosts are not sent through the codec. The codec rejects empty labels and labels over 63 characters, which WHATWG accepts for ASCII names (`https://a..b/` gives `a..b`), so running ASCII hosts through it would add rejections the crawler does not make.
- **Errors.** ValueError and UnicodeError are caught around the parse, the same way the crawler's `try/catch` wraps its whole body.

**Requirement: both jobs use it.** In `fetch_hosts` (`sync-whitelist.py`, the `strip().lower()` line inside the entry loop) and in `fetch_join_hosts` (`updater-worker.py`, the same line), that expression is replaced with `normalize_host_token(str(host))`. The following `if host_value:` / `if value:` guard already skips None, so the loop needs no other change. The fetch, the User-Agents, the payload-shape handling and the error messages stay the same. `fetch_hosts` still raises `ValueError("Whitelist contained no hosts.")` when no entry survives. `list_prod_hosts` (the other `strip().lower()` in the updater, at about line 449) is deliberately left alone.

**Requirement: the fixture and the table-driven test.** A new pytest file in `tests/active` (working name `test_host_normalisation.py`), with a JSON fixture beside it (`host_tokens.json`). The fixture is a list of `{input, expected}` pairs holding the 14 pinned values, with null for None. The test has three parts:
- **Python side.** A parametrised test asserts `normalize_host_token(input) == expected` for every pair. It imports the helper after adding `engine/server` to `sys.path`, as the jobs do.
- **Node side.**
  - It runs `node --input-type=module` once, with a short inline script. The script imports `engine/crawler/dist/host-filters.js` by `file://` URL, reads the fixture inputs as JSON on stdin, maps them through `normalizeHostToken` and prints JSON on stdout.
  - The Python test then asserts that each Node result equals the expected value. Together with the Python-side assertions, that also proves Python output equals crawler output.
  - `dist/host-filters.js` imports only `node:fs`, and the crawler package is `"type": "module"`, so no `node_modules` is needed.
- **Job side.**
  - Both job files are loaded with `importlib.util.spec_from_file_location`. Their top-level code only sets up `sys.path` and parses `engine/crawler/schema.sql`, and `main()` sits behind `__name__` guards, so loading them has no side effects.
  - A payload is written to `tmp_path` and served as a `file://` URL. `urlopen` handles `file:` even with a `Request` that carries headers, so no server thread is needed.
  - One test checks that `["https://Tube.Example/", "tube.example"]` gives `{"tube.example"}` from `fetch_hosts`. It then stores that set through `ensure_whitelist_schema` + `sync_hosts` into a temporary SQLite file (never the shared `whitelist.db`) and checks the stored row.
  - A second test mixes `""`, `"."`, `"https://"` with valid entries. It asserts the invalid entries are absent, the fetch completes, and `fetch_join_hosts` returns the same set as `fetch_hosts`. It uses the dict shape (`{"data": [{"host": ...}]}`) so both payload shapes are covered.
  - The file uses no Engine fixture, so it runs in the normal `validate_tests.py` pass.

**Requirement: loud failure, never skip.** Before the Node call, the test fails with `pytest.fail` and a message naming the fix in three cases:
- `node` is not on PATH (found via `shutil.which`)
- `dist/host-filters.js` is missing
- `dist` is stale

I recommend fail-loudly over build-first. Building needs `engine/crawler/node_modules/typescript`, which a fresh worktree does not have, so build-first would add a second failure mode and would also write to the tree during a test run. The build checkpoint makes the final choice.

**Requirement: existing scripts and suite still pass.** After the build, run `test-moderation-integration.py` and `test-orchestrator-smoke.py` separately. Then run `validate_tests.py` from the worktree's `project_dir` and compare against the green baseline. The smoke test serves `whitelist.json` through `fetch_hosts`. Its plain hosts come out of the new helper unchanged, so its expectations still hold.

### Alternatives considered

- **New module (`data/hosts.py`) instead of `moderation.py`.** It would keep the file's name tied to moderation, but it adds a file and a second import line in each job. The requirements prefer the fewest files, and `moderation.py` already owns host normalisation. Rejected. The cost: at harvest, the `test_groups` entry maps the new test to all of `moderation.py`, so edits to that module will also trigger this test. That is cheap because the test needs no Engine.
- **Porting the WHATWG host parser by hand, or adding a dependency such as `idna` or a WHATWG URL library.** Either would match the crawler on more inputs. Hand-porting is a large amount of code for inputs the list does not contain, and a dependency is ruled out. Rejected in favour of `urlparse` plus the small fixes above, with the fixture as the safety net.
- **Producing the expected values with Node at test time instead of pinning them.** That would make the crawler the only oracle, and a crawler regression would pass silently. The settled design pins the WHATWG values and checks both sides against them. Kept.
- **Checking whether `dist` is stale by modification time (mtime).** See the risks below. The recommended alternative is git-based: `dist` is stale when `src/host-filters.ts` has uncommitted changes, or when its last commit is newer than the last commit of `dist/host-filters.js`. Use mtime only when the files are untracked. This avoids false failures after a checkout while still catching a source edit that was never rebuilt.
- **Sending ASCII hosts through the `idna` codec too.** Rejected. It would add rejections (empty or over-long labels) that WHATWG does not make for ASCII hosts.

### Gotchas and risks

- **An mtime-only staleness check breaks fresh clones.** `dist` appears to be tracked in git (no ignore rule). Git writes files in index order, and `dist/` sorts before `src/`, so a fresh checkout usually leaves `dist/host-filters.js` a few milliseconds *older* than `src/host-filters.ts`. A plain "dist older than src" check would then fail on a clean tree whose contents match. Hence the git-based rule recommended above. The build checkpoint should settle the rule explicitly, because "older than" in the requirements does not say how age is measured.
- **The Node side runs the compiled `dist`, not `src`.** Parity is only as good as `dist` being current, which is why the staleness check exists.
- **IDNA 2003 versus UTS #46.** Python's `idna` codec is IDNA 2003 and WHATWG uses UTS #46 (for example `ß` maps to `ss` in Python but `xn--zca` in WHATWG). This is accepted and not pinned. Adding such an input to the fixture would make the test fail by design.
- **IPv4 shorthand.** WHATWG rewrites forms such as `0x7f.1` or `127.1` to `127.0.0.1`. `urlparse` does not. Not pinned, and accepted under the "outside the fixture" limitation.
- **Forbidden host characters.** WHATWG rejects hosts containing characters such as a space, `<`, `>` or `^`. `urlparse` accepts them. A single module-level set of forbidden host code points could close this. I leave it out as speculative, and it can be added the first time a fixture input exposes the gap. This is a deliberate simplification: the ceiling is non-parity on such inputs, and the upgrade is that one constant and a check.
- **Percent-encoding and backslashes**, JS `trim()` versus Python `strip()`, and `toLowerCase()` versus `lower()` differ as listed in the accepted limitations. None is in the fixture.
- **Import side effects.** Loading `sync-whitelist.py` through importlib parses `schema.sql` at import time. If that file moves, the test errors on import rather than failing an assertion, which is at least loud.
- **Merge conflicts.** The tracked `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict on merge. Take main's copy and re-run `validate_tests.py --compare`, as stated in the requirements.

### Tradeoffs the operator is asked to accept

- **Parity is proven only for fixture inputs.** Parity on other inputs is best effort from `urlparse` + `ipaddress` + `idna`. The upgrade path is to add inputs to the fixture.
- **The test suite gains a hard dependency on `node` and a current `dist`.** When either is missing the test fails rather than skips, as required.
- **The helper sits next to a similarly named `normalize_host` with different behaviour.** The two are told apart only by name and docstring.
- **Branch 4 stores `@`, `?`, `#` and port suffixes as given, and existing rows are not rewritten.** The first updater run after the change may treat an old spelling and its new spelling as different hosts. Both points are already accepted in the requirements.

### conflicts

none

## 2026-09-26 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impact path="engine/server/data/moderation.py" element="new normalize_host_token() and its private hostname step, placed after normalize_host (line 39-63); module imports (lines 14-18) and header comment (lines 5-11)">
**What changes.** A new public `normalize_host_token(value: str) -> str | None` is added right after `normalize_host`, along with a private helper that turns `urlparse` output into what WHATWG `URL.hostname` would give. The imports gain stdlib `ipaddress`. `urlparse` is already imported at line 18, and `from __future__ import annotations` is at line 3. Any constants go at module level. The header comment (lines 5-11, "host normalization") could name both normalisers so the split is visible.

Docstring style in this file: one-line descriptive docstrings, e.g. `"""Normalize host input (lower, strip protocol/path, trim dots/spaces)."""`, with `"""Handle ..."""` on private helpers. The new docstring must say it is an exact port of the crawler's `normalizeHostToken` and differs from `normalize_host`.

Reference behaviour, checked against `engine/crawler/src/host-filters.ts:83-100`:
- `raw = value.trim().toLowerCase()`
- empty → null
- `startsWith("http://"|"https://")` → `new URL(raw).hostname.toLowerCase() || null`
- `includes("/")` → `new URL("https://"+raw).hostname...`
- else `raw.replace(/^\.+|\.+$/g, "") || null`
- the whole body is inside try/catch → null

**What depends on it.**
- The two job call sites (below) and the new test.
- The module itself is imported at startup by the Engine API (`engine/server/api/server.py:97`) and by `engine/server/data/serving_moderation.py:11`.
- Also imported by every moderation CLI/job: `instance-denylist-cli.py:21`, `channel-moderation-cli.py:23`, `compare-join-hosts.py:23`, `sync-whitelist.py:26`, `updater-worker.py:27`, and `tests/test-moderation-integration.py:31`.
- So a syntax or import error here takes down the Engine and every job, not just the two callers.

**Regression risk: medium.** Adding a function cannot change existing callers, but parity has pitfalls:
1. `urlparse(...).hostname` returns `::1` for `https://[::1]:8080/`, so brackets must be put back (`[::1]`). Only a host containing `:` should be treated as IPv6, because `.hostname` never keeps a port.
2. Non-ASCII hosts need `.encode("idna").decode("ascii")`. This raises UnicodeError (a ValueError subclass) for invalid labels, and it must be caught.
3. `.port` raises ValueError for non-numeric ports or ports above 65535, and it must be read inside the try.
4. `urlsplit` behaviour depends on the Python version. CPython 3.11.4+/3.12 validate bracketed hosts (`_check_bracketed_host`) and strip leading C0/space characters. The interpreter that runs the tests (`validate_tests.py` uses `sys.executable` or pixi) may differ from the one that runs the jobs in production (docs use `./venv/bin/python3`; systemd units may use something else). Parity is proven only on the test interpreter.
5. `ipaddress.IPv6Address` accepts scope ids (`fe80::1%eth0`) that WHATWG rejects (outside the fixture, accepted).
6. Branch 4 must strip only `.` characters (`str.strip(".")`), not whitespace, after the initial strip/lower. It must never call the parser.

Because the Engine imports this module at startup, keep the new code free of module-level work beyond constants.
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host() (lines 39-63), unchanged, and its callers purge_host_data / purge_similarity_for_host / collect_similarity_host_stats / _row_host (lines 162, 199, 250, 414)">
**What changes.** Nothing. The requirements forbid touching it.

**What depends on it.**
- Denylist and channel CLIs (`instance-denylist-cli.py:145`, `channel-moderation-cli.py:78`).
- The updater's stale-host purge: `updater-worker.purge_hosts` → `purge_host_data`/`purge_similarity_for_host` normalise each stale host again through `normalize_host` before `DELETE ... WHERE host = ?`.
- Serving-time filtering (`_row_host`).

**Regression risk: low, but there is an interaction to record.** After this build, join hosts use the crawler spelling (`[::1]`, `xn--...`), while `normalize_host` returns IPv6 without brackets (`urlparse('https://[::1]').hostname` → `::1`) and does not punycode.

So a stale IPv6 host `[::1]` computed by the updater would be purged as `::1` and silently match no rows. A denylist entry typed as a unicode IDN would never match the punycode join host.

This is pre-existing and explicitly out of scope ("Known limitations, accepted"). The two functions now sit side by side with different contracts. A later reader must not "fix" one by merging it into the other; the new docstring is the guard.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="module-level import `from data.moderation import ensure_moderation_schema, list_active_denied_hosts` (line 26)">
**What changes.** `normalize_host_token` is added to this single-line import.

**What depends on it.** Everything in the module. It sits after the `sys.path` setup (lines 16-22) that puts `engine/server` and `engine/server/api` at `sys.path[0]`.

**Regression risk: low.** A misspelt name raises ImportError at load. The new test's importlib load would catch that immediately, as would any run of the job.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="fetch_hosts() (lines 219-250), the `host_value = str(host).strip().lower()` line 243">
**What changes.** Line 243 becomes `host_value = normalize_host_token(str(host))`. The existing `if host_value:` guard (line 244) already skips None. Everything else stays the same:
- the Request with User-Agent `peertube-graph-whitelist-sync/1.0`
- the `(HTTPError, URLError)` → RuntimeError path
- the payload-shape handling (`dict` with `"data"` / `list`, `entry.get("host")` for dicts)
- `ValueError("Unexpected whitelist JSON shape.")`
- `ValueError("Whitelist contained no hosts.")` when nothing survives

**What depends on it.**
- `main()` line 571 (`remote_hosts = fetch_hosts(args.url)`), then:
  - include mode: `selected_hosts_before_deny = remote_hosts`
  - exclude mode: `source_hosts - remote_hosts`, where `source_hosts` is `SELECT DISTINCT instance_domain FROM source.videos`, i.e. crawler-normalised
  - `- denylisted_hosts` (lines 610-612)
  - `sync_hosts(conn, selected_hosts)` (line 640)
  - `rebuild_content_tables(conn, selected_hosts)` (line 641), which copies channels/videos `WHERE instance_domain IN (hosts)`
- The new test calls it directly with a `file://` URL. `urlopen` with a `Request` works for `file:`; `timeout` is ignored.

**Regression risk: medium in behaviour, low in code.**
- Hosts that used to be stored in a non-crawler spelling now match the crawl DB. In include mode, `rebuild_content_tables` may therefore copy more channels and videos than before for such entries. In exclude mode, fewer hosts are wrongly "missing".
- `sync_hosts` deletes every `instances.host` not in the new set (lines 422-443). The first run after the change therefore replaces any old-spelling row with the new spelling in `whitelist.db`. For this table, "existing rows are not rewritten" does not really hold: it is resynced wholesale.
- If every entry normalises to None, the job still raises "Whitelist contained no hosts." (existing behaviour, required).
- `str(host)` of a non-string truthy entry (dict/bool) differs from the crawler's `extractWhitelistHost`, which only accepts string/number. That is pre-existing and outside scope.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="module top level: sys.path mutation (lines 16-22), imports of scripts.cli_format / server_config (lines 24-25), and INSTANCE_/CHANNEL_/VIDEO_COLUMNS parsed from engine/crawler/schema.sql at import (lines 36, 92-96)">
**What changes.** Nothing. This matters only because the new test loads the file through `importlib.util.spec_from_file_location` (hyphenated name, so the spec needs an identifier-like module name).

**What depends on it.**
- The test's load works only if `engine/crawler/schema.sql` exists and contains `CREATE TABLE IF NOT EXISTS instances|channels|videos` (it does).
- It also needs `engine/server/scripts/cli_format.py` (a namespace package, present) and `engine/server/api/server_config.py`. `server_config` is stdlib-only; at import it reads the env vars `ENGINE_BRIDGE_TOKEN`, `ENGINE_INGEST_MODE` and `RECOMMENDATIONS_LOG_PROFILE`.
- `main()` is behind `if __name__ == "__main__"` (line 676), so loading runs no job.

**Regression risk: low.**
- Loading inserts `engine/server` and `engine/server/api` at `sys.path[0]` for the rest of the pytest session.
- `engine/server/api/server.py` shares the module name `server` with `client/backend/server.py`, which `tests/active/conftest.py` imports as `server`. Because conftest imports it first, `sys.modules` keeps the Client's module. A later test doing a fresh `import server` still gets the cached client module, but that ordering is what keeps it safe.
- If `schema.sql` moves, the test errors at import (loud).
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="module-level parenthesised import `from data.moderation import (...)` (lines 27-32)">
**What changes.** `normalize_host_token,` is added to the parenthesised list, in alphabetical position (between `list_active_denied_hosts` and `purge_host_data`, matching the existing sorted order).

**What depends on it.** The whole module.

**Regression risk: low.** An import error would surface in the new test's importlib load.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="fetch_join_hosts() (lines 414-441), the `value = str(host).strip().lower()` line 438">
**What changes.** Line 438 becomes `value = normalize_host_token(str(host))`. The `if value:` guard (line 439) skips None. Everything else stays the same:
- User-Agent `peertube-browser-updater/1.0`
- RuntimeError message `Failed to fetch hosts from ...`
- the payload shapes
- `ValueError("Unexpected whitelist JSON shape.")`
- unlike `fetch_hosts`, no raise on an empty set (existing asymmetry, kept)

**What depends on it.** `main()` lines 829-872, under `--sync-join-whitelist`:
- `effective_join_hosts = join_hosts - denied_hosts`
- `sync_stale_hosts = prod_hosts - effective_join_hosts`
- `sync_new_hosts = effective_join_hosts - prod_hosts`
- stale hosts are then purged from prod and the similarity DB via `purge_hosts(...)`. This is a dry-run plan first, then a real `DELETE` when `--yes` is set.
- `sync_new_hosts` is written by `write_hosts_file` (line 893) to a temp file passed to the crawler as `--whitelist-file`. `engine/crawler/src/crawler.ts:24-25` → `loadHostsFromFile` → `normalizeHostToken` normalises each line again. The Python output must therefore be a fixed point of `normalizeHostToken`: `[::1]`, `xn--...` and plain hosts all go through branch 4 unchanged, so it is.
- The orchestrator smoke test drives this function end-to-end (see its entry).
- The new test calls it directly with a `file://` URL.

**Regression risk: medium-high, because this set feeds a destructive purge.**
- If the Python port returns None, or a different string, for an entry the crawler normalises to host H, then H (already in prod from the crawler) lands in `sync_stale_hosts`. With `--yes` its instances, channels, videos, embeddings and similarity rows are deleted.
- Before the change this could already happen for any entry with a scheme, a path or trailing dots. After the change it can happen only for parity gaps, such as IDNA 2003 vs UTS #46 rejections or `.port` ValueErrors on inputs WHATWG accepts. The net effect should be fewer false stale hosts, but a regression in the helper is a data-loss path, not just a mismatch.
- The first run after the change: prod rows stored under an old non-crawler spelling become stale and are purged (accepted limitation; it needs `--yes`, and `--dry-run` shows the plan).
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="list_prod_hosts() (lines 444-451) and load_denied_hosts() (lines 454-462), unchanged">
**What changes.** Nothing. `list_prod_hosts` keeps `str(row[0]).strip().lower()` by explicit decision.

**What depends on it.** It is the other operand of the stale/new set differences in `main()` (lines 831-834).

**Regression risk: low.** Prod `instances.host` rows are written by the crawler (already `normalizeHostToken` output), so strip/lower on them is the identity for normal rows.

An asymmetry remains: a prod row with trailing dots or a scheme (only possible from older Python-written rows) is not normalised on this side, so it shows up as stale. That is covered by the "existing rows not rewritten" limitation.

The denied hosts come from `list_active_denied_hosts` (lowercased rows stored via `normalize_host`), so an IDN or IPv6 denylist entry may not match the new join spelling (accepted limitation).
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="module top level (lines 1-33) and `if __name__ == \"__main__\"` guard (line 1161)">
**What changes.** Nothing beyond the import.

**What depends on it.** The new test loads this file through importlib. Its top level only mutates `sys.path` (adds `engine/server`) and imports `scripts.cli_format` and `data.moderation`. `server_config` is imported lazily inside `parse_args`. `resolve_default_engine_service_name` (which shells out to bash) runs only from `main`/`parse_args` (line 283).

**Regression risk: low.** One correction to the plan: unlike `sync-whitelist.py`, this module does NOT parse `schema.sql` at import. The plan's "their top-level code only sets up sys.path and parses schema.sql" applies to `sync-whitelist.py` only.
</impact>
<impact path="engine/crawler/src/host-filters.ts" element="normalizeHostToken() (lines 83-100), the reference; loadHostsFromFile() (lines 10-22)">
**What changes.** Nothing. Changing crawler behaviour is out of scope.

**What depends on it.**
- `crawler.ts:8,258,353` (`fetchWhitelistHosts` → `parseHostString`)
- `loadHostsFromFile`, used by `crawler.ts:25,27`, `channels-worker.ts:74,108`, `videos-worker.ts:150,209,234`, `channels-videos-count-worker.ts:44`
- `engine/crawler/excluded-hosts.txt` (its comment says entries are normalised by it)
- The new test's fixture pins its output. A future edit to this function without rebuilding `dist`, or one that changes the result for a fixture input, makes the new test fail.

**Regression risk: none from this build.** This file is the oracle. Its docstring is just "Handle normalize host token."; not touched.
</impact>
<impact path="engine/crawler/dist/host-filters.js" element="compiled normalizeHostToken (lines 81-99), executed by the new test through node">
**What changes.** Nothing is written. The new test imports it with `node --input-type=module` via a `file://` URL.

What I checked:
- Its only import is `node:fs` (line 4), so no `node_modules` is needed.
- Its `normalizeHostToken` body matches `src/host-filters.ts:83-100` line for line.
- It is tracked in git: the only ignore rule found is `node_modules/` in the root `.gitignore`.

**What depends on it.** The Node half of the parity test. Also `engine/crawler/test-url-safety.mjs:7`, which imports `toHttpUrlOrNull` from the same file (precedent).

**Regression risk: medium, for the test rather than production.**
- The "dist is stale" check decides whether the suite goes red on a clean tree.
- An mtime-only rule can false-fail after a checkout, because file write order is not guaranteed.
- The git-based rule the plan proposes needs `git` on PATH and a work tree. `.worktrees/...` is a linked worktree, where `git log -1 --format=%ct -- <path>` works but `.git` is a file, not a directory. Its failure modes (git missing, shallow clone, untracked files) must also fail loudly rather than skip.
- The build checkpoint must settle the rule.
</impact>
<impact path="engine/crawler/package.json" element="`\"type\": \"module\"` (line 4) and the `build` script (line 8: `node node_modules/typescript/bin/tsc -p tsconfig.json`)">
**What changes.** Nothing.

**What depends on it.**
- `"type": "module"` is why `dist/*.js` loads as ESM under node. The test's `--input-type=module` inline script uses dynamic `import()` of a `file://` URL.
- The fail-loud message should name the fix (`cd engine/crawler && npm install && npm run build`).

**Regression risk: low.** I confirmed `engine/crawler/node_modules/typescript` is absent in this worktree. A build-first variant therefore cannot work here, which supports fail-loudly.
</impact>
<impact path="engine/crawler/src/crawler.ts" element="fetchWhitelistHosts() / extractWhitelistEntries() / extractWhitelistHost() / parseHostString() (lines 246-304, 352-354)">
**What changes.** Nothing. This is the crawler's own reader of the same JoinPeerTube payload, and the behaviour the Python readers are meant to match.

**What depends on it.** `instances-cli` (the updater calls it with `--whitelist-url` or `--whitelist-file`).

**Regression risk: none from this build.** Differences in entry extraction remain outside the port and are not in scope:
- The crawler accepts only string/number hosts and trims before normalising.
- Python does `str(host)` on any truthy value.
- The crawler raises `Unexpected whitelist JSON shape.` for a dict without an array `data`. Python accepts `"data" in payload` of any type.

Also unchanged: `parseHost` (line 340) returns `ref.host.toLowerCase()` without `normalizeHostToken`, as noted in `docs/project/security-audit/run-2/REPORT.md:217`.
</impact>
<impact path="engine/server/db/jobs/compare-join-hosts.py" element="hosts_from_payload() line 80 and load_local_hosts() line 96 (`str(...).strip().lower()`)">
**What changes.** Nothing. It is explicitly out of scope.

**What depends on it.** The operator diagnostic that compares JoinPeerTube hosts with local `instances`.

**Regression risk: low, but it drifts.** After this build it is the only Python reader of the JoinPeerTube list still using plain strip/lower. It can report "missing" hosts that the updater and sync now treat as present (e.g. `https://x/` vs `x`). Worth a follow-up roadmap note, not a change here.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="standalone smoke script: load_hosts_from_json() (lines 347-382, own strip/lower at 375), start_whitelist_server() (396-408), run_orchestrator() (411+), payload build (964-985)">
**What changes.** Nothing in the file (its own strip/lower reader is out of scope). It must still pass after the build.

**Correction to the plan.** The smoke test does NOT go through `fetch_hosts`. It serves `whitelist.json` (`{"total", "data": [{"host": ...}]}`) over `python -m http.server` and runs `updater-worker.py --whitelist-url ...` (lines 419-441). That exercises `fetch_join_hosts`.

Its hosts come from `engine/server/db/jobs/tests/test-instances.json`: 10 plain lowercase hosts such as `videovortex.tv` and `diode.zone`, all branch-4 fixed points. They can also come from a prod DB copy, which holds crawler-normalised rows. Normalisation is therefore the identity on them and expectations hold.

**Regression risk: low for correctness.** Operationally it needs node, a built crawler `dist`, the embedding stack and network access to real instances, so running it may be constrained by the environment. That is a limitation of running the check, not a regression.
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="standalone script importing data.moderation (lines 31-38) and simulating join/stale set math">
**What changes.** Nothing. It must still pass.

**What depends on it.** It imports `ensure_moderation_schema`, `list_active_denied_hosts`, `normalize_host`, `now_ms`, `purge_host_data` and `purge_similarity_for_host`, plus `data.serving_moderation`. It does not import `fetch_join_hosts` or `sync-whitelist` (grep found no reference). Its own strip/lower readers (lines 484, 947, 1030) are its local set math.

**Regression risk: low.** It is affected only if the `moderation.py` edit breaks import or alters `normalize_host`. It runs separately from `validate_tests.py` (not in `tests/active`), per `engine/server/db/jobs/docs/MODERATION_INTEGRATION_TEST.md`.
</impact>
<impact path="engine/server/api/server.py" element="startup import `from data.moderation import ensure_moderation_schema` (line 97)">
**What changes.** Nothing in the file. The module it imports gains a function and an `ipaddress` import.

**What depends on it.** The Engine process, and therefore every Engine-backed test in `tests/active` (`engine` session fixture in `conftest.py`).

**Regression risk: very low.** Only a syntax or import error in `moderation.py` would matter, and it would stop the Engine from starting.
</impact>
<impact path="engine/server/data/serving_moderation.py" element="`from data.moderation import ModerationFilterStats, filter_rows_by_moderation` (line 11)">
**What changes.** Nothing.

**What depends on it.** Serving-time moderation filtering in the Engine and in `test-moderation-integration.py`.

**Regression risk: very low.** It is affected only by an import-time failure of `moderation.py`.
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="normalize_host usage (lines 21-25, 145); likewise engine/server/db/jobs/channel-moderation-cli.py lines 23, 78">
**What changes.** Nothing. Both are out of scope.

**What depends on it.** Operators entering denylist hosts, whose rows feed `list_active_denied_hosts`, which both jobs subtract from the normalised join set.

**Regression risk: low.** As recorded: IDN or IPv6 denylist entries are stored by `normalize_host` as unicode or unbracketed, so they may not match the new crawler-style spelling. This is pre-existing and accepted.
</impact>
<impact path="engine/server/db/jobs/tests/../../../../engine/crawler/schema.sql" element="engine/crawler/schema.sql, parsed at import time by sync-whitelist.py">
**What changes.** Nothing.

**What depends on it.** `sync-whitelist.py` lines 36 and 92-96 parse the `instances`, `channels` and `videos` column lists from it at import. The new test's importlib load of the job therefore depends on this file existing with those `CREATE TABLE IF NOT EXISTS` blocks (confirmed present at `engine/crawler/schema.sql`).

**Regression risk: low.** The test errors loudly if it moves.
</impact>
<impact path="tests/active/test_host_normalisation.py" element="new pytest file (working name)">
**What changes.** A new file. It adds `engine/server` to `sys.path` the way `tests/active/test_db.py:22-26` and `test_random_videos.py:20-28` do (a `SERVER_DIR` constant, `sys.path.insert(0, ...)`, `# noqa: E402` imports). It then imports `normalize_host_token` from `data.moderation`.

Three parts:
1. A test parametrised over the fixture.
2. A single `node --input-type=module` subprocess:
   - It first checks `shutil.which("node")`, that `dist` exists, and that `dist` is not stale, each with `pytest.fail` naming the fix.
   - The script reads fixture inputs as JSON on stdin and imports `engine/crawler/dist/host-filters.js` by `file://` URL.
   - The existing precedents (`test_frontend_*.py`) call `"node"` via PATH without a which-check. `test_frontend_profile.py:89-91` passes `PATH` through explicitly.
3. The job tests:
   - `importlib.util.spec_from_file_location` loads for both jobs (precedent: `test_similar.py:37-41`).
   - A `file://` payload in `tmp_path`.
   - `fetch_hosts` → `{"tube.example"}`, then `ensure_whitelist_schema` + `sync_hosts` into a temp SQLite file. `sync_hosts` returns a 3-tuple despite its `tuple[int, int]` annotation (line 420).
   - A mixed-invalid dict-shape payload, asserting `fetch_join_hosts == fetch_hosts`.

**What depends on it.**
- `validate_tests.py` discovers it as a group (`tests/active/test_*.py`). It is unmapped until harvest, so it runs on every invocation.
- It uses no Engine fixture, but `tests/active/conftest.py` is still imported, which imports the Client backend.

**Regression risk: low for production, medium for suite stability.**
- The node and staleness gates are the likely source of false reds.
- The docstring style of this suite is a module docstring listing each claim as bullets (see `test_similar.py:1-18` and `conftest.py:1-11`). The new file should follow it.
- It must never touch `engine/server/db/whitelist.db`, which is shared and symlinked across worktrees.
</impact>
<impact path="tests/active/host_tokens.json" element="new JSON fixture of {input, expected} pairs (14 pinned values, null for None)">
**What changes.** A new file holding the pinned values from the requirements, including `"https://bücher.example/"`, so it must be written and read as UTF-8 (`read_text(encoding="utf-8")`). The Node side receives it via stdin JSON, not a file path, so encoding must also be explicit on the subprocess (`text=True, encoding="utf-8"`). Otherwise a non-UTF-8 locale corrupts `ü`.

**What depends on it.** Both halves of the parity test.

**Regression risk: low.** It is not a `test_*.py` file, so `validate_tests.groups()` does not see it as a group. While the test is unmapped its digest does not cover the fixture, but unmapped groups always run anyway. At harvest the `test_groups` entry must list this fixture too, or an edit to it alone will not re-trigger the test.
</impact>
<impact path="tests/active/conftest.py" element="module-level imports (lines 29-41): inserts client/backend at sys.path[0], imports `server` (client) and `lib.*`; Engine fixtures">
**What changes.** Nothing.

**What depends on it.** Every test in `tests/active`, including the new one: pytest imports conftest before collecting it.

**Regression risk: low.**
- The new test's importlib loads put `engine/server/api` on `sys.path`, which contains an `http_utils.py` and a `server.py`. Client `server` and `lib` are already cached in `sys.modules` by conftest, so later imports resolve to the cached modules.
- Leaving `sys.path` mutated for the session is the same pattern `test_db.py` and `test_random_videos.py` already use.
- The new test must not request the `engine`, `engine_client` or `dataset` fixtures. Otherwise it becomes Engine-backed and subject to the one-lane rate-limit rule.
</impact>
<impact path="tests/active/test_frontend_profile.py" element="node invocation precedent (lines 65-91); also test_frontend_blocks.py:79, test_frontend_reactions.py:134/145, test_frontend_videos.py:66">
**What changes.** Nothing.

**What depends on it.** These existing tests already require `node` on the PATH seen by the pytest process. A missing node therefore already reds the suite today, which makes the new hard node dependency consistent with the suite.

**Regression risk: none.** Listed so the new test's node lookup and error message follow the existing convention.
</impact>
<impact path="engine/crawler/test-url-safety.mjs" element="standalone node harness importing ./dist/host-filters.js (line 7)">
**What changes.** Nothing.

**What depends on it.** Nothing automated: it is run by hand (`node engine/crawler/test-url-safety.mjs`), and `test-text-limits.mjs` follows the same pattern.

**Regression risk: none.** It is the precedent for running `dist/host-filters.js` directly under node without `node_modules`, and it confirms that `dist` import path works.
</impact>
<impact path=".un/skills/devsecops/scripts/validate_tests.py" element="groups() (lines 584-613), stale_reason/unmapped handling, runner() (lines 498-518)">
**What changes.** Nothing.

**What depends on it.**
- The suite run that must stay green.
- `groups()` discovers the new `test_*.py` automatically. Unmapped groups always run.
- `runner()` uses `pixi run --manifest-path` only if a `pixi.toml` / `pixienv/pixi.toml` exists in the project. None was found in this worktree, so it uses the interpreter running the script. The shebang is `pixi run python`.

**Regression risk: low.** The Python version used for the parity test is whatever this resolves to, which may differ from the job runtime's Python. That matters for `urlsplit` behaviour (see the `moderation.py` entry).
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups map (lines 14-88)">
**What changes.** Nothing in this worktree. Per the requirements, the `test_groups` entry is added at harvest on main.

That entry should map `test_host_normalisation.py` to:
- `engine/server/data/moderation.py`
- `engine/server/db/jobs/sync-whitelist.py`
- `engine/server/db/jobs/updater-worker.py`
- `engine/crawler/src/host-filters.ts`
- `engine/crawler/dist/host-filters.js`
- `tests/active/host_tokens.json`

**What depends on it.** Stale-group selection in `validate_tests.py`.

**Regression risk: low.** If the entry under-lists files (e.g. omits the fixture or `dist`), edits to those files will not re-run the test after harvest.
</impact>
<impact path="tests/last_test_validation.json" element="tracked suite record (and tests/last_test_output.txt)">
**What changes.** Both are rewritten by the post-build `validate_tests.py` run.

**What depends on it.** The baseline comparison (the baseline was green: exit 0, variant false).

**Regression risk: none functionally.** Both files are tracked and will conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
</impact>
<impact path="tests/last_test_output.txt" element="tracked captured pytest output">
**What changes.** It is rewritten by the post-build run.

**What depends on it.** Nothing in code.

**Regression risk: none.** It will conflict on merge; resolve as for `last_test_validation.json`.
</impact>

### docs_checklist

<doc path="DATA_BUILD.md">
Step 2 "Filter to JoinPeerTube whitelist" Notes (lines 145-149): add one bullet. It says each whitelist entry is normalised the way the crawler normalises hosts (`data.moderation.normalize_host_token`, a port of `normalizeHostToken`): scheme, userinfo, port and path are dropped for URL-like entries, surrounding dots are stripped, and entries that normalise to nothing are skipped.
</doc>
<doc path="engine/server/db/jobs/docs/UPDATER_WORKER.md">
"What Exactly Is Collected" (line 59, "Instances: from whitelist source"): state that with `--sync-join-whitelist` the fetched hosts are normalised with the same crawler-equivalent rule before the new/stale/denylist comparison. Also state the one-time effect: rows stored under an older spelling show up as stale on the first run, so review with `--dry-run` before `--yes`.
</doc>
<doc path="docs/project/issues/06-normalise-instance-hosts.md">
At harvest: tick the acceptance criteria, set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`. Record the accepted limitations: branch 4 keeps `@ ? #` and ports, parity is proven only for fixture inputs, and `compare-join-hosts.py` is still strip/lower.
</doc>
<doc path="docs/project/plans/10-normalise-instance-hosts.md">
At harvest: mark it delivered and point to the build plan `16-10-normalise-instance-hosts.md`. Note two corrections found in discovery: the orchestrator smoke test exercises `fetch_join_hosts` (not `fetch_hosts`), and only `sync-whitelist.py` parses `schema.sql` at import.
</doc>
<doc path="docs/project/roadmap.md">
Optional follow-up entry: bring `compare-join-hosts.py` (`hosts_from_payload`, line 80) onto `normalize_host_token` so the diagnostic agrees with the updater. Also optional: align `normalize_host` (denylist input) with bracketed IPv6 and punycode. Both are out of scope for this build.
</doc>

### highest_risk

engine/server/db/jobs/updater-worker.py fetch_join_hosts(): its output feeds `sync_stale_hosts = prod_hosts - effective_join_hosts`, which `purge_hosts` deletes from prod and similarity DBs under `--yes`. Any parity gap where the Python port returns None or a different spelling than the crawler (IDNA 2003 vs UTS #46 rejections, `.port` ValueError, a Python-version-dependent `urlsplit` difference) turns a live instance into a purged one.
tests/active/test_host_normalisation.py (node / dist-staleness gate): the fail-never-skip rule means a wrong staleness rule turns the whole suite red on clean trees. mtime ordering after checkout is unreliable; the git rule depends on git being present in a linked worktree. `node_modules/typescript` is absent here, so a stale dist cannot be rebuilt in place.
engine/server/data/moderation.py normalize_host_token(): it lives in a module the Engine imports at startup and every moderation CLI/job imports, next to a similarly named `normalize_host` with a different contract (unbracketed IPv6, no punycode). The IPv6 re-bracketing, the ASCII-only IDNA path and the error catching must be exact, and an import-time mistake takes down the Engine as well as the two jobs.

## 2026-09-26 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

I opened every file the inventory's paths name that decides whether the plan works: `moderation.py`, the crawler's `host-filters.ts` and `dist/host-filters.js`, both jobs, `crawler.ts`, the smoke and integration scripts, `conftest.py` and the test precedents, `validate_tests.py`, `package.json` and both `.gitignore` files. Every line reference and every structural claim in the inventory held up. I also traced all 14 pinned fixture values through the planned helper design by hand, and each one gives its expected value. There is one exception, and it is the only finding: the updater entry says the Python output is always left unchanged when the crawler reads it back from the `--whitelist-file` hosts file. That is false for URL-form entries whose host starts or ends with a dot. The error is small, it predates this build, and it is not a conflict with the requirements or the plan.
<question id="1">
Yes. Checked against the design: a leading or trailing dot on a bare host is stripped in branch 4 (`" Tube.Example "`, `"tube.example."`, `"..tube.example.."`). `urlparse(...).hostname` drops the scheme, port, path and userinfo (`https://Tube.Example/`, `http://tube.example:8080/path`, `https://user@tube.example`, and `tube.example/videos` through branch 3). `tube.example:9000` never reaches the parser. `::1` contains `:`, so it goes through `ipaddress.IPv6Address` and comes back as `[::1]`. `bücher.example` is not ASCII, so the `idna` codec turns it into `xn--bcher-kva.example`. `https://` gives no hostname, so it returns None. `""`, `"   "` and `"."` return None. Both call sites (`sync-whitelist.py:243`, `updater-worker.py:438`) are single `str(host).strip().lower()` lines, each followed by a truthiness guard, so returning None needs no other change. Neither job has another caller. The test's module names do not collide: `client/backend` holds only `server.py` and `lib/`, so `data`, `scripts` and `server_config` resolve to the Engine copies even after `conftest.py` puts `client/backend` first on `sys.path`. `dist/host-filters.js` exists, imports only `node:fs`, and no ignore rule excludes it (root `.gitignore` or `engine/.gitignore`). `engine/crawler/package.json` sets `"type": "module"`.
</question>
<question id="2">
The ramifications are the ones the inventory already lists. Hosts are now stored in the crawler's spelling. On the first run after the change, `whitelist.db` rows are resynced as a whole and prod rows under an old spelling are purged (with `--yes`). `normalize_host` and the new function sit side by side with different outputs for IPv6 and IDN hosts. The suite now needs `node` and an up-to-date `dist`. Parity is proven only on the test interpreter. The one addition, from reading `crawler.ts:24-25` and `host-filters.ts:96`: the updater writes `sync_new_hosts` to a file that the crawler reads back through `loadHostsFromFile`. That re-normalises each line through branch 4, which strips dots. So a JoinPeerTube entry like `https://tube.example./` becomes `tube.example.` in Python (matching the crawler's own URL mode), but the crawler stores it as `tube.example`. On the next run the prod row `tube.example` is not in the join set and is purged as stale, then recrawled. Before the change the same entry already caused a purge-and-recrawl loop, in a different spelling, so this is not a regression. The inventory's statement that the output is always left unchanged by that read-back is still wrong.
</question>
<question id="3">
Nothing beyond the plan: both import lines, both call-site lines, the helper, and the test plus its fixture. Also as planned: run `test-moderation-integration.py` and `test-orchestrator-smoke.py` separately. That smoke run exercises `fetch_join_hosts` through `updater-worker --whitelist-url` over `http.server`, as the inventory corrected, not `fetch_hosts`. Then run `validate_tests.py`. At harvest, the `test_groups` entry must list the fixture and `dist/host-filters.js`. Note that `.un/` is in the root `.gitignore`, so that config entry is local and not versioned.
</question>
<question id="4">
In both jobs, the host set changes from "trimmed and lowercased" to "exactly what `normalizeHostToken` returns". URLs collapse to their hostname. Leading and trailing dots are stripped. IPv6 hosts keep their brackets and IDN hosts become punycode. Entries that normalise to nothing are dropped where they used to be kept as junk strings. Nothing else changes: fetches, User-Agents, payload shapes, error messages, `fetch_hosts` still raising on an empty set, `list_prod_hosts`, `normalize_host`, and the crawler.
</question>

New impacts:
engine/crawler/src/host-filters.ts: `loadHostsFromFile` (lines 10-22, branch 4 at line 96) re-normalises the hosts file the updater writes (`crawler.ts:24-25`). Branch 2 and 3 outputs with a leading or trailing dot (e.g. `https://tube.example./` → `tube.example.`) are therefore NOT left unchanged: the crawler stores `tube.example`, and the next `--sync-join-whitelist` run marks that prod row as stale (purged with `--yes`) and crawls it again. Python and the crawler still agree on the value. The churn already existed before this change under a different spelling, so it is not a regression. None of the 14 fixture inputs is affected.

Inventory entries that did not hold up:
The updater `fetch_join_hosts` entry (engine/server/db/jobs/updater-worker.py) says the Python output "must therefore be a fixed point of `normalizeHostToken`: `[::1]`, `xn--...` and plain hosts all go through branch 4 unchanged, so it is". The three examples do hold. The general claim does not: `engine/crawler/src/host-filters.ts:96` strips leading and trailing dots in branch 4, while the WHATWG hostname returned by branches 2 and 3 keeps them. Every other entry matched the file at its path, including all cited line numbers and both of the inventory's corrections to the plan (the smoke test goes through `fetch_join_hosts`; only `sync-whitelist.py` parses `schema.sql` at import).

Conflicts: none

Recommendations: 1. Take the plan as it stands. The new impact does not change the design: the settled requirement is exact parity with `normalizeHostToken`, and stripping dots in the port would break that. Cost: none.
2. Fix the updater entry's wording to say branch-2/3 outputs with a leading or trailing dot are not left unchanged when the crawler reads the hosts file back, and add a roadmap note beside the planned `compare-join-hosts.py` follow-up. That follow-up is to make the crawler's file mode and URL mode agree, a crawler change that is out of scope here. Cost: one line in the inventory and one roadmap line. No code.
3. Optionally, pin one more fixture pair, `"https://tube.example./"` → `"tube.example."`, so the test records this behaviour on both the Python and Node sides. Cost: one fixture line. It adds no failure mode, because WHATWG, `urlparse` and the crawler all keep the dot. Do not take this if the pinned set is meant to stay at exactly the 14 values in the requirements.
4. At harvest, note that `.un/` and `pixi*` are both in the root `.gitignore`. The `test_groups` entry in `.un/skills/devsecops/config.json` is local-only on main, and main's `validate_tests.py` may pick a pixi interpreter (via `pixi.toml`) where this worktree used `sys.executable`. Re-running `validate_tests.py --compare` on main, which the plan already requires, covers the interpreter difference. Cost: none beyond that planned run.

## 2026-09-26 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="engine/server/data/moderation.py" element="new normalize_host_token() and its private hostname step, placed after normalize_host (lines 39-63); module imports (lines 14-18); header comment (lines 5-11)">
**What changes.** A new public `normalize_host_token(value: str) -> str | None` goes directly after `normalize_host`, with one private helper that turns `urlparse` output into what WHATWG `URL.hostname` would give. The imports gain stdlib `ipaddress`. `urlparse` is already imported (line 18) and `from __future__ import annotations` is at line 3. Any constants go at module level. The header comment's "host normalization" bullet (line 9) may name both normalisers so the split is visible.

Docstring style in this file is one-line and descriptive (e.g. line 40, `"""Normalize host input (lower, strip protocol/path, trim dots/spaces)."""`), with `"""Handle ..."""` on private helpers (lines 323, 340). The new docstring must say the function is an exact port of the crawler's `normalizeHostToken` and differs from `normalize_host`.

Reference behaviour, checked against `engine/crawler/src/host-filters.ts:83-100`:
- `raw = value.trim().toLowerCase()`; empty → null
- starts with `http://` or `https://` → `new URL(raw).hostname.toLowerCase() || null`
- contains `/` → `new URL("https://" + raw).hostname.toLowerCase() || null`
- otherwise `raw.replace(/^\.+|\.+$/g, "") || null`
- the whole body is inside try/catch → null

**What depends on it.**
- The two job call sites (entries below) and the new test.
- The module is imported at Engine startup (`engine/server/api/server.py:97`) and by `engine/server/data/serving_moderation.py:11`.
- It is also imported by `instance-denylist-cli.py:21`, `channel-moderation-cli.py:23`, `compare-join-hosts.py:23`, `sync-whitelist.py:26`, `updater-worker.py:27` and `jobs/tests/test-moderation-integration.py:31`. A syntax or import error here therefore takes down the Engine and every job, not just the two callers.

**Regression risk: medium.** Adding a function changes no existing caller, but getting parity right has pitfalls:
1. `urlparse('https://[::1]:8080/').hostname` gives `::1`, so the brackets must be put back. Only a host containing `:` is treated as IPv6, because `.hostname` never keeps the port.
2. Non-ASCII hosts go through `.encode("idna").decode("ascii")`. That raises UnicodeError (a ValueError subclass) on invalid labels, and it must be caught. ASCII hosts must NOT go through the codec, because it rejects empty or over-63-character labels that WHATWG accepts.
3. `.port` raises ValueError for a non-numeric port or one above 65535, so it must be read inside the try.
4. `urlsplit` behaviour varies with the CPython version: bracketed-host validation and stripping of leading C0 characters and spaces changed in 3.11.4/3.12. Parity is proven only on the interpreter that runs the test, which may not be the job runtime (docs use `./venv/bin/python3`).
5. `ipaddress.IPv6Address` accepts scope ids (`fe80::1%eth0`) that WHATWG rejects. This is outside the fixture and accepted.
6. Branch 4 strips only `.` (`str.strip(".")`) after the initial strip/lower and never calls the parser.
7. The WHATWG hostname returned by branches 2 and 3 keeps a leading or trailing dot (`https://tube.example./` → `tube.example.`), and so does `urlparse`. The port must NOT strip it. Stripping would break exact parity (see the host-filters read-back entry).

The Engine imports this module at startup, so the new code must do no module-level work beyond defining constants.
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host() (lines 39-63), unchanged, and its callers purge_host_data (162), purge_similarity_for_host (199), collect_similarity_host_stats (250), _row_host (414)">
**What changes.** Nothing. The requirements forbid touching it.

**What depends on it.**
- The denylist and channel CLIs (`instance-denylist-cli.py:145`, `channel-moderation-cli.py:78`).
- The updater's stale-host purge: `updater-worker.purge_hosts` (lines 484-516) passes each stale host to `purge_host_data` / `purge_similarity_for_host`, which re-normalise it through `normalize_host` before `DELETE ... WHERE host = ?`.
- Serving-time filtering (`_row_host`).

**Regression risk: low, but there is an interaction to record.** Join hosts now use the crawler's spelling (`[::1]`, `xn--...`). `normalize_host` returns IPv6 without brackets and does no punycode conversion. A stale `[::1]` would therefore be purged as `::1` and match no rows, and a denylist entry typed as a unicode IDN never matches the punycode join host. Both are pre-existing and accepted as known limitations. The two functions now sit side by side with different contracts; the new docstring is what stops a later reader from merging them.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="module-level import `from data.moderation import ensure_moderation_schema, list_active_denied_hosts` (line 26)">
**What changes.** `normalize_host_token` is added to this single-line import.

**What depends on it.** The whole module. The import sits after the `sys.path` setup (lines 16-22), which puts `engine/server` and `engine/server/api` at `sys.path[0]`.

**Regression risk: low.** A misspelt name raises ImportError at load, which the new test's importlib load and any run of the job both catch.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="fetch_hosts() (lines 219-250), the line `host_value = str(host).strip().lower()` (243)">
**What changes.** Line 243 becomes `host_value = normalize_host_token(str(host))`. The `if host_value:` guard on line 244 already skips None. Everything else stays the same:
- the User-Agent `peertube-graph-whitelist-sync/1.0`
- `(HTTPError, URLError)` → RuntimeError
- the payload shapes (a dict with `"data"`, or a list; `entry.get("host")` for dicts)
- `ValueError("Unexpected whitelist JSON shape.")`
- `ValueError("Whitelist contained no hosts.")` when no entry survives

**What depends on it.**
- `main()` line 571 feeds `remote_hosts` into the rest of the job:
  - include mode: `selected_hosts_before_deny = remote_hosts` (609)
  - exclude mode: `source_hosts - remote_hosts` (607), where `source_hosts` comes from `source.videos.instance_domain` and is therefore crawler-normalised
  - `- denylisted_hosts` (610-612)
  - `sync_hosts` (640)
  - `rebuild_content_tables` (641), which copies channels, videos and embeddings `WHERE instance_domain IN (hosts)`
- The new test calls it directly with a `file://` URL. `urlopen` accepts a `Request` for `file:`, and the timeout has no effect there.

**Regression risk: medium in behaviour, low in code.**
- Entries that used to keep a non-crawler spelling now match the crawl DB. In include mode `rebuild_content_tables` may copy more rows for them; in exclude mode fewer hosts show up as falsely "missing".
- `sync_hosts` (lines 420-445) deletes every `instances.host` row not in the new set. On the first run, old-spelling rows in `whitelist.db` are therefore replaced wholesale.
- If every entry normalises to None, the job still raises "Whitelist contained no hosts.", as the requirements require.
- `str(host)` on a truthy non-string entry (dict or bool) differs from the crawler's `extractWhitelistHost` (`crawler.ts:290-304`, which accepts only strings and numbers). This predates the build and is out of scope.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="module top level: sys.path mutation (16-22), imports of scripts.cli_format and server_config (24-25), INSTANCE_/CHANNEL_/VIDEO_COLUMNS parsed from engine/crawler/schema.sql at import (36, 92-96), __main__ guard (676)">
**What changes.** Nothing. This matters only because the new test loads the file through `importlib.util.spec_from_file_location`. The filename is hyphenated, so the spec needs an identifier-like module name.

**What depends on it.**
- The load works only if `engine/crawler/schema.sql` has the `instances`, `channels` and `videos` `CREATE TABLE IF NOT EXISTS` blocks.
- It also needs `engine/server/scripts/cli_format.py` and `engine/server/api/server_config.py`.
- `main()` runs only under `if __name__ == "__main__"` (line 676), so loading starts no job.

**Regression risk: low.**
- Loading leaves `engine/server` and `engine/server/api` on `sys.path` for the rest of the pytest session.
- `engine/server/api/server.py` has the same module name, `server`, as `client/backend/server.py`, which `tests/active/conftest.py` imports first. `sys.modules` keeps the Client module, so later imports stay safe, but only because of that ordering.
- If `schema.sql` moves, the test errors at import. That is a loud failure.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="sync_hosts() (lines 420-445) and ensure_whitelist_schema() (253-267), used by the new test">
**What changes.** Nothing.

**What depends on it.** The new acceptance test stores the fetched set through `ensure_whitelist_schema` and `sync_hosts` into a temporary SQLite file.

**Regression risk: low.** `sync_hosts` is annotated `tuple[int, int]` but returns a 3-tuple `(total, removed, added)` (line 445). The test must not unpack it as a pair. It also needs a plain connection, since there is no `row_factory` requirement here. It must never open the shared `engine/server/db/whitelist.db`.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="module-level parenthesised import `from data.moderation import (...)` (lines 27-32)">
**What changes.** `normalize_host_token,` is added in alphabetical position, between `list_active_denied_hosts` and `purge_host_data`, since the existing list is sorted.

**What depends on it.** The whole module.

**Regression risk: low.** An import error would show up at the new test's importlib load.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="fetch_join_hosts() (lines 414-441), the line `value = str(host).strip().lower()` (438)">
**What changes.** Line 438 becomes `value = normalize_host_token(str(host))`. The `if value:` guard on line 439 skips None. Everything else stays the same:
- the User-Agent `peertube-browser-updater/1.0`
- the RuntimeError `Failed to fetch hosts from ...`
- the payload shapes
- `ValueError("Unexpected whitelist JSON shape.")`
- unlike `fetch_hosts`, it still does not raise on an empty set (an existing asymmetry, kept)

**What depends on it.** `main()` lines 829-872, under `--sync-join-whitelist`:
- `effective_join_hosts = join_hosts - denied_hosts` (831)
- `sync_stale_hosts = prod_hosts - effective_join_hosts` (833)
- `sync_new_hosts = effective_join_hosts - prod_hosts` (834)
- the stale hosts go to `purge_hosts(...)`: a dry-run plan first, then real deletes from the prod and similarity DBs when `--yes` is passed (843-872)
- `sync_new_hosts` is written by `write_hosts_file` (line 893) and handed to the crawler as `--whitelist-file` (915), where `loadHostsFromFile` re-normalises it (see the host-filters read-back entry)
- the orchestrator smoke test drives this function end-to-end, and the new test calls it directly with a `file://` URL

**Correction to the earlier inventory.** The earlier entry said the Python output is always a fixed point of `normalizeHostToken`. That is false. Plain hosts, `[::1]` and `xn--...` do pass through branch 4 unchanged. But a branch-2/3 result with a leading or trailing dot (`https://tube.example./` → `tube.example.`, matching WHATWG and the crawler's URL mode) is stripped to `tube.example` when the crawler reads the hosts file back.

**Regression risk: medium-high, because this set feeds a destructive purge.**
- Suppose the port returns None or a different spelling for an entry the crawler normalises to host H. Then H, already in prod, lands in `sync_stale_hosts`, and with `--yes` its instances, channels, videos, embeddings and similarity rows are deleted.
- Before this change, that already happened for any entry with a scheme, a path or trailing dots. After it, only parity gaps can cause it: IDNA 2003 vs UTS #46, a `.port` ValueError on input WHATWG accepts, or a `urlsplit` difference between Python versions. The net effect should be fewer false stale hosts, but a bug in the helper is a data-loss path, not a cosmetic mismatch.
- On the first run after the change, prod rows stored under an old non-crawler spelling become stale and are purged. This is accepted; it needs `--yes`, and `--dry-run` shows the plan.
- The dotted-URL churn described in the read-back entry predates this build and is not a regression.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="write_hosts_file() (lines 465-481) and its two callers (888 exclude file, 893 whitelist file → --whitelist-file at 915)">
**What changes.** Nothing in the code. What it writes changes: `sync_new_hosts` now holds `normalize_host_token` output, one host per line, sorted, UTF-8.

**What depends on it.** The crawler's `instances-cli --whitelist-file` → `crawler.ts:24-25` → `loadHostsFromFile`, which trims each line, skips blanks and `#` lines, and runs `normalizeHostToken` again.

**Regression risk: low.** For almost every value the second normalisation changes nothing. The one exception is a URL-form entry whose host has a leading or trailing dot, which becomes a different string in prod than in the join set (see the read-back entry). A host starting with `#` would be dropped as a comment. That can only come from branch 4, which keeps `#`, it predates this build, and it is accepted.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="list_prod_hosts() (lines 444-451) and load_denied_hosts() (454-462), unchanged">
**What changes.** Nothing. `list_prod_hosts` keeps `str(row[0]).strip().lower()` by explicit decision.

**What depends on it.** It is the other side of the stale/new set differences in `main()` (lines 831-834).

**Regression risk: low.**
- Prod `instances.host` rows are written by the crawler, so strip/lower is the identity on normal rows. A row written earlier by Python with dots or a scheme would show up as stale; that falls under the "existing rows not rewritten" limitation.
- The denied hosts come from `list_active_denied_hosts` (rows stored via `normalize_host`), so IDN and IPv6 denylist entries may not match the new spelling. This is accepted.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="module top level (lines 1-33) and __main__ guard (1161)">
**What changes.** Nothing beyond the import.

**What depends on it.** The new test's importlib load. The top level only:
- mutates `sys.path` (adding `engine/server`)
- imports stdlib modules, `scripts.cli_format` and `data.moderation`

`server_config` is imported lazily inside `parse_args` (lines 85-89), and `resolve_default_engine_service_name`, which runs bash, is only reached from `parse_args`/`main`.

**Regression risk: low.** A correction to the plan: this module does NOT parse `schema.sql` at import (it does so only inside `main`, line 788). Only `sync-whitelist.py` does.
</impact>
<impact path="engine/crawler/src/host-filters.ts" element="normalizeHostToken() (lines 83-100), the reference implementation, unchanged">
**What changes.** Nothing. Changing crawler behaviour is out of scope.

**What depends on it.**
- `crawler.ts:8, 258, 353`: `fetchWhitelistHosts` → `parseHostString` → `normalizeHostToken`.
- `loadHostsFromFile` (see the next entry).
- The new fixture pins its output. If this function is edited without rebuilding `dist`, or edited so that a fixture result changes, the new test fails.

**Regression risk: none from this build.** It is the oracle. Its docstring, "Handle normalize host token.", is not touched.
</impact>
<impact path="engine/crawler/src/host-filters.ts" element="loadHostsFromFile() (lines 10-22): re-normalisation of the updater's --whitelist-file (the read-back)">
**What changes.** Nothing in the file. This entry records a behaviour the earlier inventory got wrong.

**What depends on it.** `crawler.ts:25` (whitelist file) and `crawler.ts:27` (exclude file). It is also used as the exclude-hosts reader by `channels-worker.ts:74, 108`, `videos-worker.ts:150, 209, 234` and `channels-videos-count-worker.ts:44`.

**The read-back is not always an identity.** Each line goes through `normalizeHostToken`, and a bare host takes branch 4, which strips leading and trailing dots (line 96). The updater writes `normalize_host_token` output, which for URL-form entries is a WHATWG hostname that may end in a dot. Worked through:
- JoinPeerTube entry `https://tube.example./` → Python and the crawler's URL mode give `tube.example.`
- the file-mode crawl stores `tube.example`
- the next `--sync-join-whitelist` run finds prod `tube.example` missing from the join set → it is marked stale (purged with `--yes`) and recrawled

Python and the crawler still agree on the value, which is the requirement. The churn existed before this change under a different spelling (the old strip/lower kept `https://tube.example./` as-is), so it is not a regression. None of the 14 pinned inputs is affected.

**Regression risk: low.** Fixing it means making the crawler's file mode and URL mode agree. That is a crawler change and out of scope; it is recorded for the roadmap.
</impact>
<impact path="engine/crawler/dist/host-filters.js" element="compiled normalizeHostToken (lines 81-99), run by the new test through node">
**What changes.** Nothing is written. The new test imports it with `node --input-type=module` via a `file://` URL.

**Checked:**
- Its only import is `node:fs` (line 4), so no `node_modules` is needed.
- The body matches `src/host-filters.ts:83-100` line for line.
- No ignore rule excludes it: the root `.gitignore` ignores `node_modules/` and `engine/.gitignore` ignores only `.pixi/*`.

**What depends on it.** The Node half of the parity test. `engine/crawler/test-url-safety.mjs:7` already imports `./dist/host-filters.js` directly, which is the precedent.

**Regression risk: medium, for the suite rather than production.**
- The "dist is stale" rule decides whether a clean tree goes red. An mtime-only rule can false-fail after a checkout.
- The git-based rule needs `git` on PATH. This is a linked worktree, where `.git` is a file; `git log -1 --format=%ct -- <path>` still works there.
- Failure modes such as git missing, a shallow clone, or untracked files must fail loudly, never skip.
- The build checkpoint must settle the rule.
</impact>
<impact path="engine/crawler/package.json" element="`&quot;type&quot;: &quot;module&quot;` (line 4) and the build script (line 8: `node node_modules/typescript/bin/tsc -p tsconfig.json`)">
**What changes.** Nothing.

**What depends on it.**
- `"type": "module"` is why `dist/*.js` loads as ESM.
- The fail-loud message should name the fix: `cd engine/crawler && npm install && npm run build`.

**Regression risk: low.** A build-first variant would need `node_modules/typescript`, which a fresh worktree lacks. That supports fail-loudly.
</impact>
<impact path="engine/crawler/src/crawler.ts" element="crawl() whitelist source (lines 23-36), fetchWhitelistHosts() (246-269), extractWhitelistEntries() (274-285), extractWhitelistHost() (290-304), parseHost() (334-347), parseHostString() (352-354)">
**What changes.** Nothing. This is the crawler's own reader of the same payload, the behaviour the Python readers must match.

**What depends on it.** `instances-cli`, which the updater runs with `--whitelist-file` (or `--whitelist-url`).

**Regression risk: none from this build.** Differences outside the port stay as they are:
- The crawler accepts only string or number hosts and trims before normalising; Python calls `str(host)` on any truthy value.
- The crawler raises `Unexpected whitelist JSON shape.` for a dict whose `data` is not an array; Python accepts `"data" in payload` whatever its type.
- `parseHost` returns `ref.host.toLowerCase()` without normalising (line 340).
</impact>
<impact path="engine/server/db/jobs/compare-join-hosts.py" element="hosts_from_payload() (line 80) and load_local_hosts() (line 96), both `str(...).strip().lower()`">
**What changes.** Nothing. Explicitly out of scope.

**What depends on it.** The operator diagnostic that compares JoinPeerTube hosts with the local `instances` table.

**Regression risk: low, but it drifts.** After this build it is the only Python reader of the list that still uses strip/lower. It can report hosts as "missing" (`https://x/` vs `x`) that the jobs now treat as present. This is a roadmap follow-up.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="load_hosts_from_json() (lines ~347-382, own strip/lower at 375), start_whitelist_server() (~396-408), run_orchestrator() (411-450), payload build (964-985)">
**What changes.** Nothing in the file. It must still pass.

**Correction to the plan.** The smoke test does NOT go through `fetch_hosts`. It writes `whitelist.json` (`{"total", "data": [{"host": ...}]}`), serves it with `python -m http.server`, and runs `updater-worker.py --whitelist-url` (lines 419-441). That exercises `fetch_join_hosts`.

The hosts come from `engine/server/db/jobs/tests/test-instances.json` (per `ORCHESTRATOR_SMOKE_TEST.md:42`) or from prod rows, which are plain crawler-normalised hosts that pass through the helper unchanged. Its expectations therefore hold.

**Regression risk: low for correctness.** Running it needs node, a built `dist`, the embedding stack and network access. That limits whether it can be run here, but it is not a regression.
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="standalone script importing data.moderation (lines 31-38)">
**What changes.** Nothing. It must still pass.

**What depends on it.** It imports `ensure_moderation_schema`, `list_active_denied_hosts`, `normalize_host`, `now_ms`, `purge_host_data` and `purge_similarity_for_host`, plus `data.serving_moderation`. It does not import either job. Its own strip/lower calls (lines 484, 947, 1030) are local set arithmetic.

**Regression risk: low.** It can break only if the `moderation.py` edit fails to import or alters `normalize_host`. It is run separately from `validate_tests.py`.
</impact>
<impact path="engine/server/api/server.py" element="startup import `from data.moderation import ensure_moderation_schema` (line 97)">
**What changes.** Nothing in the file. The module it imports gains a function and an `ipaddress` import.

**What depends on it.** The Engine process, and so every Engine-backed test through the `engine` fixture in `conftest.py`.

**Regression risk: very low.** Only an import-time failure of `moderation.py` matters, and it would stop the Engine from starting.
</impact>
<impact path="engine/server/data/serving_moderation.py" element="`from data.moderation import ModerationFilterStats, filter_rows_by_moderation` (line 11)">
**What changes.** Nothing.

**What depends on it.** Serving-time moderation in the Engine and in the integration script.

**Regression risk: very low.** It is affected only by an import-time failure of `moderation.py`.
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="normalize_host usage (import at line 21, call at 145)">
**What changes.** Nothing. Out of scope.

**What depends on it.** The operator's denylist entries, which feed `list_active_denied_hosts`. Both jobs subtract that set from the normalised join set.

**Regression risk: low.** IDN and IPv6 entries are stored in unicode or without brackets, so they may not match the new crawler-style spelling. This predates the build and is accepted.
</impact>
<impact path="engine/server/db/jobs/channel-moderation-cli.py" element="normalize_host usage (import at line 23, call at 78)">
**What changes.** Nothing. Out of scope.

**What depends on it.** `channel_moderation.instance_domain` rows, which serving-time filtering compares with `normalize_host(row host)`.

**Regression risk: none from this build.** It never reads the output of `normalize_host_token`.
</impact>
<impact path="engine/crawler/schema.sql" element="instances/channels/videos CREATE TABLE blocks, parsed at import by sync-whitelist.py">
**What changes.** Nothing.

**What depends on it.** `sync-whitelist.py` (lines 36 and 92-96) parses these blocks at import, so the new test's importlib load depends on this file.

**Regression risk: low.** If it moves or changes, the test errors loudly.
</impact>
<impact path="tests/active/test_host_normalisation.py" element="new pytest file (working name)">
**What changes.** A new file.
- It puts `engine/server` on `sys.path` the way `test_db.py:22-26` and `test_random_videos.py:19-24` do (a `SERVER_DIR` constant, `sys.path.insert(0, ...)`, `# noqa: E402` imports), then imports `normalize_host_token` from `data.moderation`.
- **Part 1:** a test parametrised over the fixture pairs.
- **Part 2:** one `node --input-type=module` subprocess.
  - Before it runs, `pytest.fail` with a message naming the fix if `shutil.which("node")` finds nothing, if `dist/host-filters.js` is missing, or if `dist` is stale.
  - The inline script reads the fixture inputs as JSON on stdin and imports the `dist` module by `file://` URL.
  - The existing precedents (`test_frontend_*.py`) call `"node"` without a which-check.
- **Part 3:** the job tests.
  - Load both jobs with `importlib.util.spec_from_file_location` (precedent: `test_similar.py:36-41`).
  - Serve a `file://` payload from `tmp_path`.
  - `fetch_hosts` returns `{"tube.example"}`, which is then stored through `ensure_whitelist_schema` + `sync_hosts` into a temp DB (3-tuple return).
  - A mixed-invalid, dict-shape payload asserts `fetch_join_hosts == fetch_hosts`.

**What depends on it.** `validate_tests.groups()` picks it up automatically (`tests/active/test_*.py`). It is unmapped until harvest, so it runs on every invocation. It uses no Engine fixture, but pytest still imports `conftest.py`, which imports the Client backend.

**Regression risk: low for production, medium for suite stability.**
- The node and staleness gates are the likely source of false reds.
- The module docstring should follow the suite's style: a summary line, then bullets for each claim, as in `test_similar.py:1-18` and `test_db.py:1-8`.
- It must never touch `engine/server/db/whitelist.db`, which is shared across worktrees.
- It must not request the `engine`, `engine_client`, `unpublished_client` or `dataset` fixtures.
</impact>
<impact path="tests/active/host_tokens.json" element="new JSON fixture of {input, expected} pairs (14 pinned values, null for None)">
**What changes.** A new file holding the pinned pairs. It includes `"https://bücher.example/"`, so it must be read with `encoding="utf-8"`, and the node subprocess needs `text=True, encoding="utf-8"`. Otherwise a non-UTF-8 locale corrupts the `ü`.

Optional extra pair from step 4: `"https://tube.example./"` → `"tube.example."`. It pins the dot-keeping URL behaviour on both sides. WHATWG, `urlparse` and the crawler all agree on it, so it adds no failure mode. Leave it out if the set must stay at exactly the 14 required values.

**What depends on it.** Both halves of the parity test.

**Regression risk: low.** It is not a `test_*.py` file, so it is not a group. At harvest the `test_groups` entry must list it, or an edit to the fixture alone will not re-run the test.
</impact>
<impact path="tests/active/conftest.py" element="module-level imports (lines 29-41: client/backend inserted at sys.path[0], `import server`, `lib.*`); Engine fixtures">
**What changes.** Nothing.

**What depends on it.** Every test in `tests/active`, including the new one.

**Regression risk: low.** The job loads put `engine/server/api` (which holds `server.py`, `http_utils.py`, `server_config.py`) on `sys.path`. By then conftest has already cached the Client's `server` and `lib` in `sys.modules`. `client/backend` holds only `server.py` and `lib/`, so `data`, `scripts` and `server_config` resolve to the Engine copies. The new test leaves `sys.path` mutated, the same as existing tests do.
</impact>
<impact path="tests/active/test_frontend_videos.py" element="node invocation precedent (line 66); also test_frontend_blocks.py:79, test_frontend_profile.py:70, test_frontend_reactions.py:134/145">
**What changes.** Nothing.

**What depends on it.** These tests already need `node` on the PATH that pytest sees, so the suite already goes red without node. The new hard dependency is consistent with that.

**Regression risk: none.** Listed so the new test's node call and its message follow the existing convention.
</impact>
<impact path="engine/crawler/test-url-safety.mjs" element="standalone node harness importing ./dist/host-filters.js (line 7)">
**What changes.** Nothing.

**What depends on it.** Nothing automated: it is run by hand, as is `test-text-limits.mjs`.

**Regression risk: none.** It shows that `dist/host-filters.js` loads under plain node with no `node_modules`.
</impact>
<impact path=".un/skills/devsecops/scripts/validate_tests.py" element="groups() (584-613), claimed()/digest (616-677), runner() (498-518)">
**What changes.** Nothing.

**What depends on it.** The suite run that must stay green:
- `groups()` discovers the new `test_*.py`, and an unmapped group always runs.
- `claimed()` digests only the test file plus its mapped files, so the fixture is covered only once it is mapped.
- `runner()` uses `pixi run --manifest-path` only if `pixi.toml` or `pixienv/pixi.toml` exists. Neither exists in this worktree (checked the root and `engine/`), so it uses `sys.executable`.

**Regression risk: low.** The Python version that proves parity depends on this runner and may differ from the job runtime.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups map (lines 14-88)">
**What changes.** Nothing in this worktree. The entry is added at harvest on main. It should map `test_host_normalisation.py` to:
- `engine/server/data/moderation.py`
- `engine/server/db/jobs/sync-whitelist.py`
- `engine/server/db/jobs/updater-worker.py`
- `engine/crawler/src/host-filters.ts`
- `engine/crawler/dist/host-filters.js`
- `tests/active/host_tokens.json`

**What depends on it.** Stale-group selection.

**Regression risk: low.** An entry that lists too few files misses re-runs. Also, `.un/` is in the root `.gitignore`, so this config is local and not versioned.
</impact>
<impact path="tests/last_test_validation.json" element="tracked suite record">
**What changes.** It is rewritten by the post-build `validate_tests.py` run.

**What depends on it.** The comparison against the baseline (green: code 0, variant false).

**Regression risk: none functionally.** It will conflict on merge: take main's copy and re-run `validate_tests.py --compare` on the merged tree.
</impact>
<impact path="tests/last_test_output.txt" element="tracked captured pytest output">
**What changes.** It is rewritten by the post-build run.

**What depends on it.** Nothing in code.

**Regression risk: none.** Resolve its merge conflict the same way as `last_test_validation.json`.
</impact>


### docs_checklist

<doc path="DATA_BUILD.md">
Section "2) Filter to JoinPeerTube whitelist", Notes (lines 145-149): add one bullet. It should say that each whitelist entry is normalised the way the crawler normalises hosts (`data.moderation.normalize_host_token`, a port of `normalizeHostToken`):
- URL-like entries lose the scheme, userinfo, port and path.
- Bare entries lose leading and trailing dots.
- Entries that normalise to nothing are skipped.
</doc>
<doc path="engine/server/db/jobs/docs/UPDATER_WORKER.md">
"What Exactly Is Collected" (line 59, "Instances: from whitelist source"): state that with `--sync-join-whitelist` the fetched hosts are normalised by the same crawler-equivalent rule before the new/stale/denylist comparison. State the one-time effect: rows stored under an older spelling show up as stale on the first run, so review them with `--dry-run` before `--yes`. The "Important Flags" list (lines 101-115) could also gain `--sync-join-whitelist`, `--yes` and `--dry-run`, which it currently omits.
</doc>
<doc path="docs/project/issues/06-normalise-instance-hosts.md">
At harvest:
- Tick the acceptance criteria.
- Set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.
- Record the accepted limitations: branch 4 keeps `@ ? #` and ports; parity is proven only for fixture inputs; `compare-join-hosts.py` still uses strip/lower; the file-mode read-back strips dots from URL-form hosts that end in a dot.
</doc>
<doc path="docs/project/plans/10-normalise-instance-hosts.md">
At harvest: mark it delivered and point to `16-10-normalise-instance-hosts.md`. Note the corrections found in discovery:
- The orchestrator smoke test exercises `fetch_join_hosts`, not `fetch_hosts`.
- Only `sync-whitelist.py` parses `schema.sql` at import.
- The updater's hosts file is not always left unchanged when the crawler reads it back (dotted URL-form hosts).
</doc>
<doc path="docs/project/roadmap.md">
Follow-up entries, all out of scope for this build:
- Move `compare-join-hosts.py` (`hosts_from_payload`, line 80) onto `normalize_host_token`.
- Make the crawler's `--whitelist-file` mode (`loadHostsFromFile`, branch 4 strips dots) and its URL mode (keeps the WHATWG trailing dot) agree, so dotted entries stop churning through purge and recrawl.
- Optionally, align `normalize_host` (denylist input) on bracketed IPv6 and punycode.
</doc>

### highest_risk

engine/server/db/jobs/updater-worker.py fetch_join_hosts(): its output feeds `sync_stale_hosts = prod_hosts - effective_join_hosts`, and `purge_hosts` deletes those hosts from the prod and similarity DBs under `--yes`. Any parity gap where the port returns None or a different spelling than the crawler (IDNA 2003 vs UTS #46, a `.port` ValueError, a `urlsplit` difference between Python versions) turns a live instance into a purged one. The file-mode read-back also means that even exact parity can change the spelling of dotted URL-form hosts.
tests/active/test_host_normalisation.py (the node and dist-staleness gate): because the test must fail rather than skip, a wrong staleness rule turns the suite red on clean trees. An mtime order after checkout is unreliable, and the git-based rule depends on git in a linked worktree. `node_modules/typescript` is absent, so a stale `dist` cannot be rebuilt in place.
engine/server/data/moderation.py normalize_host_token(): the Engine imports this module at startup and so does every moderation CLI and job, and the new function sits beside `normalize_host`, which has a different contract. The IPv6 re-bracketing, the ASCII-only IDNA path, keeping the WHATWG trailing dot and the error catching must all be exact, and an import-time mistake takes down the Engine as well as both jobs.

## 2026-09-26 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: none.

I checked the inventory against the files it names: `moderation.py`, both jobs, `host-filters.ts` and its `dist` build, `package.json`, `crawler.ts`, the smoke test, `conftest.py`, the test precedents in `tests/active`, `validate_tests.py` and the `.gitignore` files. Every entry held up, including the corrections the inventory makes to the plan: the smoke test goes through `fetch_join_hosts`, not `fetch_hosts`; only `sync-whitelist.py` parses `schema.sql` when it is imported; `sync_hosts` returns 3 values; and the crawler's file read-back strips dots. The plan holds as written. The only issues I found are inside the helper and the test (how the Node script receives its input, and how IPv6 addresses are printed on different Python versions). Neither changes which files are touched, so they are recommendations, not new impacts.
<question id="1">
Yes. At `sync-whitelist.py:243` and `updater-worker.py:438` the helper call is a drop-in replacement for the current line, and the `if host_value:` / `if value:` guards that follow already skip None. `moderation.py` already imports `urlparse` (line 18) and has `from __future__ import annotations` (line 3), so the helper needs only `ipaddress` and the stdlib `idna` codec. I compared the four branches against `host-filters.ts:83-100`, and `dist/host-filters.js` imports only `node:fs`. The test plan is also feasible:
- `urlopen` reads `file://` URLs.
- Both jobs run `main()` only under a `__main__` guard, so loading them has no side effects.
- The fixture can be read with `encoding="utf-8"`.

One implementation detail matters: the Node script must be passed with `-e` (`--eval`) so that stdin stays free for the fixture inputs. See the recommendations.
</question>
<question id="2">
- **Both jobs now spell hosts the crawler's way.** In include mode, `rebuild_content_tables` may copy more rows for entries that used a non-crawler spelling before. In exclude mode, fewer hosts show up as falsely missing.
- **One-time churn on the first run.** `whitelist.db` rows stored under an old spelling are replaced by `sync_hosts`. Prod rows stored under an old spelling become stale, and `purge_hosts` deletes them, but only with `--yes` (lines 856-872).
- **A helper bug can delete data.** The updater's stale set feeds a destructive purge, so a helper that returns None or a different spelling for a valid entry can cause data loss.
- **The test suite gains a hard dependency on `node` and an up-to-date `dist`.** The frontend tests already require node (`test_frontend_*.py`).
- **Two normalisers with different rules now sit in the same module.** Denylist entries typed as IDN or IPv6 still don't match the join-host spelling. This was already true before and is an accepted limitation.
- **Unchanged paths.** Outside `--sync-join-whitelist`, the updater still passes `--whitelist-url` to the crawler (line 917), which is unaffected.
</question>
<question id="3">
Nothing beyond what the plan already does:
- `normalize_host` and `list_prod_hosts` stay untouched.
- The helper does no work at import time (the Engine imports this module at startup, `server.py:97`).
- ValueError and UnicodeError are caught around the whole parse, including the `.port` read.
- `test-moderation-integration.py` and `test-orchestrator-smoke.py` are run separately. `test-instances.json` contains no host with a scheme, path, uppercase letter or dot at either end, so the smoke test's hosts come through unchanged.
- The full `validate_tests.py` run is compared against the green baseline.
- At harvest, the `test_groups` entry lists the fixture and both `host-filters` files.
- The merge conflicts in `tests/last_test_*` are resolved by taking main's copy and re-running `validate_tests.py --compare`.
</question>
<question id="4">
- **Stored values change.** `fetch_hosts` and `fetch_join_hosts` now return the crawler's `normalizeHostToken` result instead of `strip().lower()`. URL-form entries are stored as the bare hostname, IPv6 as `[..]`, IDNs as punycode.
- **Invalid entries are dropped instead of stored:** `.`, `https://`, a bad port, bad IPv6, bad IDNA.
- **Everything else is unchanged:** the error messages, the User-Agents, the accepted payload shapes, "Whitelist contained no hosts.", and the asymmetry where the updater does not raise on an empty set.
- **`moderation.py` only gains a function.** No existing caller's behaviour changes.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Pass the Node script with `node --input-type=module -e <script>` and send the fixture inputs on stdin.** The script reads them with `fs.readFileSync(0, "utf8")`. `--input-type` applies only to `--eval` or stdin, so if the script itself is piped on stdin, the inputs have no channel left. Cost: none; it only settles how the inline script is invoked.

2. **Name one more Python-version parity gap in the helper's accepted limitations.** Python 3.13 changed how IPv4-mapped IPv6 addresses are printed: `str(IPv6Address("::ffff:7f00:1"))` now gives `::ffff:127.0.0.1`, while WHATWG gives `[::ffff:7f00:1]`. This belongs next to the existing `urlsplit` version risk in the `moderation.py` entry. Cost: one line of documentation. Closing the gap instead would cost a branch on `.ipv4_mapped` that formats the last 32 bits as two hex groups (about 3 lines). I recommend documenting it, not closing it: the input is not in the fixture, and closing it is speculative.

3. **Settle the dist-staleness rule at the build checkpoint as the plan's git-based rule.** It needs `git` on PATH, and if git is missing or a file is untracked the test must fail loudly, not fall back silently. Cost: about 10 lines of subprocess code. It avoids false failures on a fresh clone, where an mtime-only rule would fail the test.

4. **Add the optional `"https://tube.example./"` → `"tube.example."` pair to the fixture only if the requirements allow more than the 14 required values.** It pins the dot-keeping URL behaviour that the read-back entry depends on. Cost: one fixture line, and no new ways for the test to fail.

5. **Use `conftest.ROOT` to build paths in the new test,** as `test_similar.py:25` does, rather than recomputing the repository root. Cost: none.

## 2026-09-26 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Module map

| File | Change |
|---|---|
| `engine/server/data/moderation.py` | adds `import ipaddress`, the constant `URL_SCHEME_PREFIXES`, `normalize_host_token()` and the private `_whatwg_hostname()` directly after `normalize_host`; the header bullet names both normalisers |
| `engine/server/db/jobs/sync-whitelist.py` | line 26 import gains `normalize_host_token`; `fetch_hosts` line 243 swapped |
| `engine/server/db/jobs/updater-worker.py` | the parenthesised import gains `normalize_host_token,` between `list_active_denied_hosts` and `purge_host_data`; `fetch_join_hosts` line 438 swapped |
| `tests/active/host_tokens.json` | new, 15 `{input, expected}` pairs |
| `tests/active/test_host_normalisation.py` | new, 5 tests: Python table, Node table, three job tests |
| `DATA_BUILD.md`, `engine/server/db/jobs/docs/UPDATER_WORKER.md` | one note each (text below) |

No new file under `engine/`, no dependency, no new interface. The issue, plan and roadmap doc edits happen at harvest, as settled.

## What the build needs to test

1. `normalize_host_token` returns the pinned value for every fixture input. That covers all four branches, userinfo, port, IPv6 brackets, punycode, and the None cases.
2. The crawler's compiled `normalizeHostToken` returns the same pinned values, so Python == crawler on the fixture.
3. The test fails loudly when `node` is missing, `dist/host-filters.js` is missing, or `dist` is stale.
4. `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` into `{"tube.example"}`, and `sync_hosts` stores that one row in a temporary DB.
5. Entries that normalise to None are dropped, the fetch completes, and `fetch_join_hosts` == `fetch_hosts` on a dict-shape payload.
6. `fetch_hosts` still raises `Whitelist contained no hosts.` when every entry normalises to None. This is existing behaviour the requirements restate, and it costs one assert.

`test-moderation-integration.py`, `test-orchestrator-smoke.py` and `validate_tests.py` are run, not changed.

## `engine/server/data/moderation.py`

Header comment, line 9:

```python
# - host normalization (normalize_host for operator input, normalize_host_token for hosts-list entries, a port of the crawler's normalizeHostToken),
```

Imports, alphabetical in the existing block:

```python
import ipaddress
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
```

Module constant, placed after the imports and before `ModerationFilterStats`:

```python
URL_SCHEME_PREFIXES = ("http://", "https://")
```

New code directly after `normalize_host`:

```python
def normalize_host_token(value: str) -> str | None:
    """Normalize a hosts-list entry exactly as the crawler's normalizeHostToken (engine/crawler/src/host-filters.ts) does; unlike normalize_host, bare entries keep ports and URL entries yield the WHATWG hostname."""
    raw = value.strip().lower()
    if not raw:
        return None
    try:
        if raw.startswith(URL_SCHEME_PREFIXES):
            return _whatwg_hostname(raw)
        if "/" in raw:
            return _whatwg_hostname(f"https://{raw}")
        return raw.strip(".") or None
    except ValueError:
        return None


def _whatwg_hostname(url: str) -> str | None:
    """Handle the hostname WHATWG URL.hostname returns for url; raise ValueError where WHATWG throws."""
    parsed = urlparse(url)
    # Reading .port raises ValueError on a non-numeric or out-of-range port, which WHATWG also rejects.
    _ = parsed.port
    host = parsed.hostname or ""
    if not host:
        return None
    if ":" in host:
        return f"[{ipaddress.IPv6Address(host).compressed}]"
    if not host.isascii():
        host = host.encode("idna").decode("ascii")
    return host.lower() or None
```

Invariants and decisions:
- **Order.** The branch order and tests match `host-filters.ts:83-100` exactly. `raw.strip(".")` is `replace(/^\.+|\.+$/g, "")`. Branch 4 never parses, so `tube.example:9000`, `@`, `?`, `#` and non-ASCII characters pass through unchanged.
- **One except.** A single `except ValueError` stands in for the crawler's whole-body try/catch. It also catches `UnicodeError` (idna), `ipaddress.AddressValueError`, urlsplit's `Invalid IPv6 URL`, and the `.port` error, because all of them subclass ValueError.
- **IPv6.** It is detected by `":" in host`. `.hostname` never carries the port, so a colon can only come from an IPv6 literal. `.compressed` is the form WHATWG serialises, and the brackets are put back.
- **IDNA only for non-ASCII.** Only non-ASCII hosts go through the `idna` codec. ASCII hosts skip it, so `a..b` and labels over 63 characters are kept, as WHATWG keeps them.
- **Dots kept.** A trailing or leading dot in a URL-form host is kept (`https://tube.example./` → `tube.example.`), exactly as WHATWG keeps it. The fixture pins this.
- **Nothing at import.** There is no module-level work beyond the tuple constant, because the Engine imports this module at startup.
- **`normalize_host` untouched.**

## Job call sites

`sync-whitelist.py` line 26:

```python
from data.moderation import ensure_moderation_schema, list_active_denied_hosts, normalize_host_token
```

`fetch_hosts`, line 243 only:

```python
        host_value = normalize_host_token(str(host))
```

`updater-worker.py` import:

```python
from data.moderation import (
    ensure_moderation_schema,
    list_active_denied_hosts,
    normalize_host_token,
    purge_host_data,
    purge_similarity_for_host,
)
```

`fetch_join_hosts`, line 438 only:

```python
        value = normalize_host_token(str(host))
```

The existing `if host_value:` / `if value:` guards already skip None. The User-Agents, error types and messages, payload-shape handling, the empty-set raise in `fetch_hosts` and the missing one in `fetch_join_hosts` are all unchanged. `list_prod_hosts` is untouched.

## `tests/active/host_tokens.json`

```json
[
  {"input": " Tube.Example ", "expected": "tube.example"},
  {"input": "tube.example.", "expected": "tube.example"},
  {"input": "..tube.example..", "expected": "tube.example"},
  {"input": "https://Tube.Example/", "expected": "tube.example"},
  {"input": "http://tube.example:8080/path", "expected": "tube.example"},
  {"input": "https://user@tube.example", "expected": "tube.example"},
  {"input": "tube.example/videos", "expected": "tube.example"},
  {"input": "tube.example:9000", "expected": "tube.example:9000"},
  {"input": "https://[::1]:8080/", "expected": "[::1]"},
  {"input": "https://bücher.example/", "expected": "xn--bcher-kva.example"},
  {"input": "", "expected": null},
  {"input": "   ", "expected": null},
  {"input": ".", "expected": null},
  {"input": "https://", "expected": null},
  {"input": "https://tube.example./", "expected": "tube.example."}
]
```

The file holds the 14 required pairs plus the optional dot-keeping pair from step 4. WHATWG, `urlparse` and the crawler all agree on that pair, and it guards against a later "fix" that strips the dot in the port. It is saved as UTF-8 (`ü` written raw), and all inputs are unique, which the Node assertion relies on.

## `tests/active/test_host_normalisation.py`

```python
"""The Engine's port of the crawler's host normalisation, and the two jobs that read the JoinPeerTube hosts list through it.

- `data.moderation.normalize_host_token` returns the pinned value for every pair in `host_tokens.json`.
- The crawler's compiled `normalizeHostToken` (`engine/crawler/dist/host-filters.js`, run under node) returns the same pinned values, so the Python port and the crawler agree on every fixture input. A missing node, a missing dist or a dist older than `src/host-filters.ts` fails the test, never skips it.
- The whitelist sync job's host fetch turns `https://Tube.Example/` and `tube.example` into the single host `tube.example`, which `sync_hosts` stores as one row.
- Entries that normalise to nothing are left out of both jobs' host sets, the fetch still completes, and the updater's join-host fetch returns the same set as the sync job's.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest
from conftest import ROOT

SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import normalize_host_token  # noqa: E402

JOBS_DIR = SERVER_DIR / "db" / "jobs"
CRAWLER_DIR = ROOT / "engine" / "crawler"
SRC = CRAWLER_DIR / "src" / "host-filters.ts"
DIST = CRAWLER_DIR / "dist" / "host-filters.js"
BUILD_HINT = "cd engine/crawler && npm install && npm run build"
FIXTURE = ROOT / "tests" / "active" / "host_tokens.json"
PAIRS = json.loads(FIXTURE.read_text(encoding="utf-8"))
# Reads a JSON list of inputs on stdin and prints the crawler's normalizeHostToken of each.
NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);
const inputs = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));
"""


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jobs():
    return _load_job("sync_whitelist_job", "sync-whitelist.py"), _load_job("updater_worker_job", "updater-worker.py")


def _payload_url(tmp_path, payload) -> str:
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.as_uri()


def _commit_time(git: str, path) -> int | None:
    out = subprocess.run([git, "log", "-1", "--format=%ct", "--", str(path)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    return int(out) if out else None


def _dist_staleness() -> str | None:
    """Return why dist/host-filters.js is behind src/host-filters.ts, or None when it is current."""
    git = shutil.which("git")
    if git is None:
        return "git is not on PATH, so the freshness of dist/host-filters.js cannot be checked"
    src_dirty = subprocess.run([git, "status", "--porcelain", "--", str(SRC)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    src_time = _commit_time(git, SRC)
    dist_time = _commit_time(git, DIST)
    # An uncommitted or untracked source is judged by mtime; committed files by commit time, which a checkout does not reorder.
    if src_dirty or src_time is None or dist_time is None:
        if DIST.stat().st_mtime < SRC.stat().st_mtime:
            return "dist/host-filters.js is older on disk than the edited src/host-filters.ts"
        return None
    if src_time > dist_time:
        return "src/host-filters.ts was committed after dist/host-filters.js was last rebuilt and committed"
    return None


@pytest.mark.parametrize("pair", PAIRS, ids=[repr(pair["input"]) for pair in PAIRS])
def test_python_port_returns_pinned_value(pair):
    assert normalize_host_token(pair["input"]) == pair["expected"]


def test_crawler_dist_returns_pinned_values():
    node = shutil.which("node")
    if node is None:
        pytest.fail(f"node is not on PATH; install Node.js, then run: {BUILD_HINT}")
    if not DIST.is_file():
        pytest.fail(f"{DIST} is missing; run: {BUILD_HINT}")
    stale = _dist_staleness()
    if stale:
        pytest.fail(f"{stale}; run: {BUILD_HINT}")
    inputs = [pair["input"] for pair in PAIRS]
    proc = subprocess.run(
        [node, "--input-type=module", "-e", NODE_SCRIPT], input=json.dumps(inputs), capture_output=True, text=True, encoding="utf-8", timeout=60,
        env={**os.environ, "HOST_FILTERS_URL": DIST.as_uri()},
    )
    assert proc.returncode == 0, proc.stderr
    assert dict(zip(inputs, json.loads(proc.stdout))) == {pair["input"]: pair["expected"] for pair in PAIRS}


def test_sync_job_stores_one_spelling_per_host(jobs, tmp_path):
    sync, _ = jobs
    hosts = sync.fetch_hosts(_payload_url(tmp_path, ["https://Tube.Example/", "tube.example"]))
    assert hosts == {"tube.example"}
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        sync.ensure_whitelist_schema(conn)
        # sync_hosts returns (total, removed, added) despite its two-element annotation.
        counts = sync.sync_hosts(conn, hosts)
        conn.commit()
        stored = [row[0] for row in conn.execute(f"SELECT host FROM {sync.TABLE_NAME}")]
    finally:
        conn.close()
    assert counts == (1, 0, 1)
    assert stored == ["tube.example"]


def test_jobs_drop_entries_that_normalise_to_nothing(jobs, tmp_path):
    sync, updater = jobs
    entries = ["", "   ", ".", "https://", "https://Tube.Example/", "other.example."]
    url = _payload_url(tmp_path, {"data": [{"host": entry} for entry in entries]})
    expected = {"tube.example", "other.example"}
    assert sync.fetch_hosts(url) == expected
    assert updater.fetch_join_hosts(url) == expected


def test_sync_job_still_rejects_a_list_with_no_usable_host(jobs, tmp_path):
    sync, _ = jobs
    with pytest.raises(ValueError, match="Whitelist contained no hosts."):
        sync.fetch_hosts(_payload_url(tmp_path, ["   ", ".", "https://"]))
```

Seams and decisions in the test:
- **Fixture paths.** `ROOT` comes from `conftest`, as `test_similar.py` uses it. `SERVER_DIR` and the `# noqa: E402` import follow `test_db.py:22-26`. The file uses no Engine fixture, so it runs in the normal `validate_tests.py` pass.
- **Loading the jobs.** Both are loaded through `spec_from_file_location` with identifier-like module names, following `test_similar.py:36-41`. Neither job defines a dataclass, so no `sys.modules` registration is needed. `main()` sits behind `__main__` guards. The module-scoped fixture loads each job once, and `sync-whitelist.py` parses `schema.sql` at that point, so if the file moves the tests error loudly.
- **Payloads.** They are served as `file://` URIs from `tmp_path`. `urlopen` accepts a `Request` with headers for `file:` and ignores the timeout, so no server thread is needed. The mixed test uses the dict shape and the first test the list shape, so both shapes are covered. `""` is dropped by the jobs' existing `if not host` before the helper runs; `"   "`, `"."` and `"https://"` reach the helper and return None.
- **Temporary database.** Every database is a `tmp_path` file. The shared `engine/server/db/whitelist.db` is never opened.
- **Node call.**
  - It uses the absolute path from `shutil.which`.
  - The dist URL is passed through the environment, which is `os.environ` plus one key, so PATH and the rest are kept.
  - `encoding="utf-8"` covers the raw `ü` in stdout under non-UTF-8 locales. stdin is ASCII because `json.dumps` escapes by default.
  - The zip into a dict makes a pytest failure show exactly which input differs.
- **Staleness rule (recommended for the build checkpoint).**
  - Committed files are compared by the last commit time of `src/host-filters.ts` versus `dist/host-filters.js`, which a fresh checkout's write order cannot disturb.
  - An uncommitted or untracked source, or a path with no history (for example a shallow boundary or untracked `dist`), falls back to mtime.
  - A missing `git`, or a git command that fails (`check=True` raises `CalledProcessError`), is a loud fail or error, never a skip.
  - Ceiling: a commit that changes only a comment in `src` without recommitting `dist` reports stale. The fix, rebuild and commit, is cheap, and a false red is preferred to a silent pass.
  - The alternative the checkpoint may pick instead is build-first. It is rejected because it needs `node_modules/typescript` and would write to the tree during a test run.

## Documentation text

`DATA_BUILD.md`, a new bullet appended to the "Notes:" list under section 2:

```markdown
- Each whitelist entry is normalised the way the crawler normalises hosts (`data.moderation.normalize_host_token`, a port of `normalizeHostToken`): URL-like entries lose the scheme, userinfo, port and path; bare entries lose leading and trailing dots; entries that normalise to nothing are skipped.
```

`UPDATER_WORKER.md`, line 59 becomes:

```markdown
- Instances: from whitelist source (JoinPeerTube URL by default). With `--sync-join-whitelist` the fetched hosts are normalised by the crawler-equivalent rule (`data.moderation.normalize_host_token`) before the new/stale/denylist comparison. Prod rows stored under an older spelling show up as stale on the first run after this change, so review the plan with `--dry-run` before passing `--yes`.
```

Under "Important Flags", add `- \`--sync-join-whitelist\`, \`--yes\`, \`--dry-run\`` after `--whitelist-url`.

## Verification commands (build step)

1. `python -m pytest tests/active/test_host_normalisation.py -q` from the worktree root.
2. `python engine/server/db/jobs/tests/test-moderation-integration.py`, then `test-orchestrator-smoke.py`. The smoke test drives `fetch_join_hosts` through `--whitelist-url`, not `fetch_hosts`, and needs node, a built `dist`, the embedding stack and network. If any of these is missing, report the run as not possible here rather than green.
3. `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts`, compared against the green baseline (code 0, variant false).

## Check against plan and requirements (pass 1: converged)

- **Helper.** It lives in `moderation.py` after `normalize_host`, which is unchanged. It is stdlib only, adds one module constant and has a one-line docstring naming the port and the difference from `normalize_host`. All four branches are in order, and branch 4 does no parse and no punycode. Traced by hand, all 15 fixture pairs give the expected value through `urlparse` / `ipaddress` / `idna`.
- **Jobs.** Only the one expression and the import change in each. `list_prod_hosts`, `compare-join-hosts.py`, the CLIs and the crawler are untouched.
- **Acceptance criteria.**
  - The Python table test and the Node test on `dist` share one fixture.
  - Fail-loudly covers node, a missing dist and a stale dist, without depending on `node_modules`.
  - The `https://Tube.Example/` + `tube.example` payload gives `{tube.example}`, stored via `sync_hosts` in a temp DB.
  - None entries are dropped while the fetch completes.
  - `fetch_join_hosts` == `fetch_hosts`.
  - The empty-set raise is kept.
- **Style.** One statement per line, no softwrap, `from __future__ import annotations` in both touched Python modules that already use it, no new dependency, no single-implementation interface.
- **Deliberate simplifications, each with its ceiling and upgrade path.**
  - Parity is proven only on the fixture and on the interpreter that runs pytest. The upgrade is to add fixture inputs.
  - There is no forbidden-host-code-point check. Upgrade: one module constant plus one test in `_whatwg_hostname`, the first time a fixture input exposes the gap.
  - IPv6 scope ids are accepted and IDNA 2003 is used, as the settled limitations state.

Nothing is left unresolved that needs the operator. The staleness rule remains for the build checkpoint to settle, as the requirements say.

## 2026-09-26 - Step 6 - Design the phase breakdown

Approved by the operator.

#### Phase 1 - Python port of normalizeHostToken [code]

**Files touched.** engine/server/data/moderation.py (EDITED), tests/active/host_tokens.json (NEW), tests/active/test_host_normalisation.py (NEW)

**Checkpoint.** Seam: the pure function `data.moderation.normalize_host_token`, called directly from pytest with `engine/server` added to sys.path, following test_db.py:22-26 (`SERVER_DIR` insert plus a `# noqa: E402` import) and `ROOT` from conftest as test_similar.py uses it. The test is parametrised over the pairs loaded at run time from `tests/active/host_tokens.json` (15 pairs, with ids from repr(input)). It asserts `normalize_host_token(input) == expected`, with JSON null standing for None. Together the pairs exercise all four branches, userinfo, port drop, port keep in branch 4, IPv6 re-bracketing, punycode, the None cases and dot keeping in URL form. It runs in the normal validate_tests.py pass because it uses no Engine fixture.

**Intent.** `engine/server/data/moderation.py` gains `normalize_host_token`, placed directly after the unchanged `normalize_host`, and it returns the pinned value for every pair in `tests/active/host_tokens.json`.

- C1 - `normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null.

**Outcome.** _pending_

#### Phase 2 - Crawler parity and loud failure [code]

**Files touched.** tests/active/test_host_normalisation.py (EDITED)

**Checkpoint.** Seam, clause 1: the crawler's compiled module `engine/crawler/dist/host-filters.js`, entered by one `node --input-type=module -e` subprocess. The subprocess imports that module by its file:// URL (passed in the HOST_FILTERS_URL env var), reads the fixture inputs as JSON on stdin and prints `normalizeHostToken` of each as JSON. The test asserts returncode 0 and that dict(zip(inputs, outputs)) equals the pinned {input: expected} map. Because phase 1 checks Python against the same map, passing this proves Python == crawler on the fixture. Seam, clause 2: the pytest outcome of the node test itself. The checkpoint runs `python -m pytest tests/active/test_host_normalisation.py -k crawler_dist` in a subprocess three times: with a PATH that lacks node, with DIST pointed at a missing path, and with a stale dist. It asserts each run reports failed, not skipped, and that the message names the build hint. The staleness rule is settled here: compare the git commit times of src/host-filters.ts and dist/host-filters.js; fall back to mtime when src has uncommitted changes or either file has no history; a missing git is a failure.

**Intent.** `test_host_normalisation.py` checks the crawler's compiled `normalizeHostToken` against the same pinned fixture, and the check cannot pass without node and a current `dist/host-filters.js`.

- C1 - `dist/host-filters.js` run under node returns each fixture pair's expected value.
- C2 - A missing node, a missing dist or a stale dist makes the crawler test fail rather than skip.

**Outcome.** _pending_

#### Phase 3 - Both jobs normalise through the helper [code]

**Files touched.** engine/server/db/jobs/sync-whitelist.py (EDITED), engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_host_normalisation.py (EDITED)

**Checkpoint.** Seam: the two jobs' fetch functions and `sync_hosts`. Both job files are loaded with importlib.util.spec_from_file_location, following the test_similar.py:36-41 precedent, in a module-scoped fixture. Payloads are served from tmp_path as file:// URIs, so no server and no network are needed. Clause 1: a list-shape payload ["https://Tube.Example/", "tube.example"] gives {"tube.example"} from `fetch_hosts`. `ensure_whitelist_schema` plus `sync_hosts` into a tmp_path SQLite file (never the shared whitelist.db) returns (1, 0, 1) and stores exactly the one row "tube.example". Clause 2: a dict-shape payload mixing "", "   ", ".", "https://" with valid entries gives {"tube.example", "other.example"} from both `fetch_hosts` and `fetch_join_hosts`. Regression guard, not a new clause: `fetch_hosts` on a payload where every entry normalises to None still raises ValueError "Whitelist contained no hosts.". After the phase, run test-moderation-integration.py, test-orchestrator-smoke.py (report it as not run if node, dist, the embedding stack or network is missing) and validate_tests.py from the worktree, compared with the green baseline.

**Intent.** `fetch_hosts` in sync-whitelist.py and `fetch_join_hosts` in updater-worker.py pass every hosts-list entry through `normalize_host_token` in place of `strip().lower()`.

- C1 - `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`, which `sync_hosts` stores as one row.
- C2 - Entries that normalise to None are dropped, and `fetch_join_hosts` returns the same host set as `fetch_hosts`.

**Outcome.** _pending_


Needs coordination: Phase 2 needs `node` on PATH in the build environment, plus a committed or rebuilt engine/crawler/dist/host-filters.js (present in the tree now). If node is missing, the checkpoint fails by design, and the operator must install Node.js and run `cd engine/crawler && npm install && npm run build`. The phase 3 post-build run of test-orchestrator-smoke.py also needs the embedding stack and network access; if either is missing, it is reported as not run, not as green. No credentials are needed.

Rationale: The split follows the three boundaries the drafted implementation already has: the pure Python function, the Node process running the compiled crawler, and the two jobs' fetch/sync functions. Each phase can be verified on its own: phase 1 needs only Python, phase 2 adds node and the dist, and phase 3 adds the job modules and SQLite. Phase 1 lands the helper with the fixture it is judged against, so the fixture exists before anything else depends on it. Phase 2 holds the two facts about the node test (parity, and failing rather than skipping). Those are two clauses on one seam, and this is where the staleness rule (git commit times, with an mtime fallback) gets settled, as the plan asks. Phase 3 holds the requirement that both jobs use the helper, as two observable facts. The existing "no hosts" raise is kept as a regression assert rather than a clause, because it is behaviour the tree already has. The doc edits (DATA_BUILD.md, UPDATER_WORKER.md) get no phase and go to Step 9. Three phases, within the limit of 4. The operator approved this breakdown unchanged.

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`engine/server/data/moderation.py` gains `normalize_host_token`, placed directly after the unchanged `normalize_host`, and it returns the pinned value for every pair in `tests/active/host_tokens.json`.

- C1 - `normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null.

must_prove:
- C1 - `normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null.

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - self-check (audit round 1, send-back 0)

`tests/tmp/test_10_normalise_instance_hosts_phase1.py`, surface `checkpoint`. Collection exit 2.

- C1 - tests/tmp/test_10_normalise_instance_hosts_phase1.py:53 — for each of the 15 pinned inputs (parametrised, ids repr(input)), `moderation.normalize_host_token(value) == expected`, with None where the pinned value is null - expected: The pinned value for each input: "tube.example" for the 7 trim/dot/scheme/userinfo/port/path inputs, "tube.example:9000", "[::1]", "xn--bcher-kva.example", "tube.example." for "https://tube.example./", and None for "", "   ", ".", "https://". These are the WHATWG values the requirements pin (plus the plan's 15th pair); I did not observe them this turn — see answers 7 and 10. - excludes: A stub returning None fails the 11 non-null cases. Reusing the unchanged `normalize_host` (by my reading of moderation.py:39-63, not a run) fails "tube.example:9000" (port dropped → "tube.example"), "https://[::1]:8080/" (→ "::1", no brackets), "https://bücher.example/" (no punycode) and "https://tube.example./" (dot stripped → "tube.example"). Bare `strip().lower()` fails every URL-form and dotted case. Stripping the dot in branches 2 and 3 fails the "https://tube.example./" case.
- C1 - tests/tmp/test_10_normalise_instance_hosts_phase1.py:47-48 — `tests/active/host_tokens.json` has exactly 15 entries, and its {input: expected} map equals PINNED (JSON null == None) - expected: 15 entries, and the map equals PINNED. That ties "each fixture pair" in C1 to the pinned pairs that line 53 checks. - excludes: If the fixture were written to match the port, both would pass by construction, and this assertion catches it. Examples: "tube.example" for "tube.example:9000", "::1" for the IPv6 input, "bücher.example" for the IDN input, or a missing or duplicated pair. Each one reads a different map or count here.

<assertions>
tests/tmp/test_10_normalise_instance_hosts_phase1.py:44 - `tests/active/host_tokens.json` has exactly 15 pairs, the number of pinned values; guards against a fixture with duplicates or extra inputs (C1)
tests/tmp/test_10_normalise_instance_hosts_phase1.py:45 - the fixture's {input: expected} map equals the 15 pairs pinned in the requirements, which the test writes out itself (JSON null == None). This means the implementer cannot pass the parametrised test by writing a fixture that matches the port's output. Wrong version: a fixture showing old strip/lower or `normalize_host` output (e.g. `tube.example` for `tube.example:9000`, `::1`, `bücher.example`) does not match. (C1)
tests/tmp/test_10_normalise_instance_hosts_phase1.py:50 - for each fixture pair (ids are repr(input)), `normalize_host_token(input) == expected`, with None where it is null. The pairs cover branch 1 (the empty and whitespace-only inputs are None), branch 2 (scheme, userinfo dropped, port dropped, IPv6 put back in brackets as `[::1]`, punycode `xn--bcher-kva.example`, `https://` is None, a trailing dot is kept in `tube.example.`), branch 3 (`tube.example/videos`), and branch 4 (dots trimmed, `.` is None, port kept in `tube.example:9000`). Wrong versions: a stub returning None fails the 11 non-null pairs. The unchanged `normalize_host` fails the port-keep, `[::1]`, punycode and dotted-URL pairs. Bare `strip().lower()` fails every URL-form pair and the dotted bare pairs. A missing function fails the import. (C1)
</assertions>

<probes>
none were run: I have no ValidateTests tool in this session, so I could not run the file or print anything. The expected values are not my own predictions. They are the 14 WHATWG values the requirements pin, plus the dot-keeping pair the plan adds to the 15-pair fixture (`https://tube.example./` → `tube.example.`). Two things would confirm them. The phase's first validate_tests.py run over this file should go red now: the fixture and `normalize_host_token` do not exist yet, so the module import or the fixture read fails at collection. Once implemented it should go green. Phase 2's Node check then confirms the pinned values against the crawler's real `normalizeHostToken` output.
</probes>

<unassertable>
none. Two deliberate changes from the Step 6 seam wording, both needed to carry C1 soundly: (1) `ROOT` is computed as `Path(__file__).resolve().parents[2]` (as test_db.py:22 does) rather than imported from conftest. `tests/tmp/` has no conftest, so `from conftest import ROOT` would fail there. The same depth resolves the same way if the file moves to `tests/active`. (2) This phase writes `host_tokens.json` too, so a test that took its expected values only from that file would pass by construction against a fixture written to match the code. The test therefore also pins the 15 pairs itself and asserts that the fixture equals them. The parametrised test still iterates over the fixture as agreed.
</unassertable>

### `tests/tmp/test_10_normalise_instance_hosts_phase1.py` - 1977 characters, inlined in full

```
"""Phase 1 checkpoint: `data.moderation.normalize_host_token`, the Engine's port of the crawler's `normalizeHostToken`.

- `tests/active/host_tokens.json` holds exactly the 15 input -> expected pairs pinned by the requirements (WHATWG `URL.hostname` values, null for None), so the fixture the port is checked against cannot drift to match the port.
- For every pair in that fixture, `normalize_host_token(input)` returns the expected value, and None where it is null.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import normalize_host_token  # noqa: E402

FIXTURE = ROOT / "tests" / "active" / "host_tokens.json"
PAIRS = json.loads(FIXTURE.read_text(encoding="utf-8"))

# The pinned values from the requirements, written out independently of the fixture the phase creates.
PINNED = {
    " Tube.Example ": "tube.example",
    "tube.example.": "tube.example",
    "..tube.example..": "tube.example",
    "https://Tube.Example/": "tube.example",
    "http://tube.example:8080/path": "tube.example",
    "https://user@tube.example": "tube.example",
    "tube.example/videos": "tube.example",
    "tube.example:9000": "tube.example:9000",
    "https://[::1]:8080/": "[::1]",
    "https://bücher.example/": "xn--bcher-kva.example",
    "": None,
    "   ": None,
    ".": None,
    "https://": None,
    "https://tube.example./": "tube.example.",
}


def test_fixture_holds_exactly_the_pinned_pairs():
    assert len(PAIRS) == len(PINNED)  # C1
    assert {pair["input"]: pair["expected"] for pair in PAIRS} == PINNED  # C1


@pytest.mark.parametrize("pair", PAIRS, ids=[repr(pair["input"]) for pair in PAIRS])
def test_normalize_host_token_returns_pinned_value(pair):
    assert normalize_host_token(pair["input"]) == pair["expected"]  # C1

```


Gate: satisfied

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - does not collect (send-back 1)

`validate_tests.py tests/tmp/test_10_normalise_instance_hosts_phase1.py --collect-only -q` exited 2.

```

==================================== ERRORS ====================================
____ ERROR collecting tests/tmp/test_10_normalise_instance_hosts_phase1.py _____
ImportError while importing test module '/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts/tests/tmp/test_10_normalise_instance_hosts_phase1.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../.pixi/envs/default/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/tmp/test_10_normalise_instance_hosts_phase1.py:19: in <module>
    from data.moderation import normalize_host_token  # noqa: E402
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ImportError: cannot import name 'normalize_host_token' from 'data.moderation' (/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts/engine/server/data/moderation.py)
=========================== short test summary info ============================
ERROR tests/tmp/test_10_normalise_instance_hosts_phase1.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
no tests collected, 1 error in 0.06s

the run produced no per-test results, so there is nothing to bucket or compare — its output above says why

recorded: tests/last_test_validation.json (exit 2)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - self-check (audit round 1, send-back 1)

`tests/tmp/test_10_normalise_instance_hosts_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_normalise_instance_hosts_phase1.py:53 — for each of the 15 pinned inputs (parametrised, ids repr(input)), `moderation.normalize_host_token(value) == expected`, with None where the pinned value is null - expected: The pinned value for each input. "tube.example" for the 7 trim, dot, scheme, userinfo, port and path inputs. "tube.example:9000", "[::1]" and "xn--bcher-kva.example". "tube.example." for "https://tube.example./". None for "", "   ", "." and "https://". The first 14 are the WHATWG values pinned in the operator-confirmed requirements. The 15th comes from the approved plan's fixture. No run has shown me any of them; see answers 7 and 10. - excludes: A stub returning None fails the 11 non-null cases. Reusing the unchanged `normalize_host` fails "tube.example:9000" (port dropped, giving "tube.example"), "https://[::1]:8080/" (gives "::1" with no brackets), "https://bücher.example/" (no punycode) and "https://tube.example./" (dot stripped, giving "tube.example"); I got this from reading moderation.py:39-63, not from a run. Bare `strip().lower()` fails every URL-form case and every dotted case. Stripping the dot in branches 2 and 3 fails the "https://tube.example./" case.
- C1 - tests/tmp/test_10_normalise_instance_hosts_phase1.py:47-48 — `tests/active/host_tokens.json`, read at run time, has exactly 15 entries, and its {input: expected} map equals PINNED (JSON null == None) - expected: 15 entries, and a map equal to PINNED. This makes "each fixture pair" in C1 exactly the pairs that line 53 checks. - excludes: A fixture written to match the port's output would let line 53 and a fixture-driven test pass by construction. Such a fixture gives a different map here: "tube.example" for "tube.example:9000", "::1" for the IPv6 input, "bücher.example" for the IDN input. A fixture holding only the 14 required pairs, or one with a duplicated or extra pair, gives a different count or map.

<assertions>
tests/tmp/test_10_normalise_instance_hosts_phase1.py:47 - `tests/active/host_tokens.json`, read when the test runs (line 46, utf-8), has exactly 15 entries, one for each pinned pair. This catches a fixture with a missing, extra or duplicated pair. Wrong version: a fixture that holds only the 14 required pairs, or repeats one, fails. Today the file does not exist, so line 46 raises FileNotFoundError. (C1)
tests/tmp/test_10_normalise_instance_hosts_phase1.py:48 - the fixture's {input: expected} map equals PINNED, the 15 pairs the test writes out itself at lines 25-41, with JSON null == None. This makes "each fixture pair" in C1 the same set of pairs line 53 checks, so an implementer cannot write a fixture to match the port's output and pass. Wrong version: a fixture holding strip/lower or `normalize_host` output (`tube.example` for `tube.example:9000`, `::1` for the IPv6 input, `bücher.example` for the IDN input, `tube.example` for `https://tube.example./`) gives a different map. (C1)
tests/tmp/test_10_normalise_instance_hosts_phase1.py:53 - for each of the 15 pinned inputs (parametrised, ids from repr(input)), `moderation.normalize_host_token(value) == expected`, with None where the pinned value is null. The pairs cover every branch. Branch 1: `""` and `"   "` → None. Branch 2: scheme and case; userinfo dropped; port dropped (`http://tube.example:8080/path`); IPv6 re-bracketed (`https://[::1]:8080/` → `[::1]`); punycode (`https://bücher.example/` → `xn--bcher-kva.example`); `https://` → None; the URL-form dot kept (`https://tube.example./` → `tube.example.`). Branch 3: `tube.example/videos`. Branch 4: dots trimmed, `.` → None, port kept (`tube.example:9000`). Wrong versions: a stub returning None fails the 11 non-null cases. Reusing the unchanged `normalize_host` fails the port-keep, `[::1]`, punycode and dotted-URL cases (from reading moderation.py:39-63). Bare `strip().lower()` fails every URL-form case and the dotted bare cases. Today the function does not exist, so each case fails with AttributeError on `data.moderation`, not with a collection error, because the module is imported rather than the name. (C1)
</assertions>

<probes>
I ran no probe of my own: this session has no ValidateTests tool, so I could not run anything under tests/tmp. The only thing I observed is the workflow's collect-only run of the previous version. It exited 2 with `ImportError: cannot import name 'normalize_host_token' from 'data.moderation' (/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts/engine/server/data/moderation.py)`. That shows `ROOT = Path(__file__).resolve().parents[2]` plus the `SERVER_DIR` insert resolve `data.moderation` to the worktree's engine/server module, and that the missing name, not a path, is what failed. Fix: the file now imports the module (`import data.moderation as moderation`, line 20), reads the fixture inside the test (line 46), and parametrises over the literal PINNED, so nothing at import time needs this phase's code. Expected collect count, not observed: 16 (1 fixture test plus 15 cases). Expected red on the current tree, also not observed: FileNotFoundError at line 46, and AttributeError at line 53 in all 15 cases. Both are this phase's missing deliverables. The 15 expected values are not observed either. 14 are the WHATWG values the requirements pin, and the 15th (`https://tube.example./` → `tube.example.`) comes from the plan. They can be confirmed by running the crawler's `dist/host-filters.js` `normalizeHostToken` over the same inputs, which is phase 2's C1, or by this checkpoint going green after implementation.
</probes>

<unassertable>
none. C1 is fully carried. The test differs from the Step 6 seam wording in two ways, both needed to collect and to avoid passing by construction. (1) The parametrised test runs over the literal PINNED, not over the fixture's pairs. `tests/active/host_tokens.json` does not exist until this phase writes it, and parametrisation runs at collection, so parametrising over the fixture fails collection (the exit 2 above), as would the draft's module-level `json.loads`. The fixture is still read at run time, and line 48 asserts that its pairs equal PINNED, so every fixture pair is checked at line 53, with the ids still from repr(input). This also stops the implementer from writing a fixture that matches the port. My previous reply said the parametrised test "still iterates over the fixture"; that was inaccurate and is corrected here. (2) `ROOT` is computed as `Path(__file__).resolve().parents[2]`, as test_db.py does, and not imported from conftest. `tests/tmp/` has no conftest, and the collect-only output shows this resolves `engine/server` correctly.
</unassertable>

### `tests/tmp/test_10_normalise_instance_hosts_phase1.py` - 2284 characters, inlined in full

```
"""Phase 1 checkpoint: `data.moderation.normalize_host_token`, the Engine's port of the crawler's `normalizeHostToken`.

- `tests/active/host_tokens.json` holds exactly the 15 input -> expected pairs pinned by the requirements (WHATWG `URL.hostname` values, null for None), so the fixture the port is checked against cannot drift to match the port.
- For every pinned pair, and so for every pair in that fixture, `normalize_host_token(input)` returns the expected value, and None where it is null.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# The module, not the name: the phase adds the function, so a missing one must fail each case rather than the whole file's collection.
import data.moderation as moderation  # noqa: E402

FIXTURE = ROOT / "tests" / "active" / "host_tokens.json"

# The pinned values from the requirements, written out independently of the fixture the phase creates.
PINNED = {
    " Tube.Example ": "tube.example",
    "tube.example.": "tube.example",
    "..tube.example..": "tube.example",
    "https://Tube.Example/": "tube.example",
    "http://tube.example:8080/path": "tube.example",
    "https://user@tube.example": "tube.example",
    "tube.example/videos": "tube.example",
    "tube.example:9000": "tube.example:9000",
    "https://[::1]:8080/": "[::1]",
    "https://bücher.example/": "xn--bcher-kva.example",
    "": None,
    "   ": None,
    ".": None,
    "https://": None,
    "https://tube.example./": "tube.example.",
}


def test_fixture_holds_exactly_the_pinned_pairs():
    # Read at run time: the phase creates the fixture, so reading it at import would stop collection instead of failing this test.
    pairs = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(pairs) == len(PINNED)  # C1
    assert {pair["input"]: pair["expected"] for pair in pairs} == PINNED  # C1


@pytest.mark.parametrize("value,expected", PINNED.items(), ids=[repr(value) for value in PINNED])
def test_normalize_host_token_returns_pinned_value(value, expected):
    assert moderation.normalize_host_token(value) == expected  # C1

```


Gate: satisfied

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - red (audit round 1)

`tests/tmp/test_10_normalise_instance_hosts_phase1.py` exited 1.

```
  tests/tmp/test_10_normalise_instance_hosts_phase1.py  16 failed                              0.0s
  ----------------------------------------------------
  total                                                 16 failed                              0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this; nearest entry is hardcoded-spec-mirror (rules/shape.md) — tests/tmp/test_10_normalise_instance_hosts_phase1.py:48
   assert {pair["input"]: pair["expected"] for pair in pairs} == PINNED  # C1
   This compares a JSON test-data file to the inline `PINNED` literal. If one changes, the other
   must change too, which is the lockstep `hardcoded-spec-mirror <why_bad>` describes. But that
   entry's <how_to_spot> covers a *code constant*, and `host_tokens.json` is a test fixture, so
   the entry does not apply as written. I am reporting it because no rule covers mirroring test
   data. The assertion itself is at the correct rung: it parses the JSON and checks typed values
   (rung 4) against a structured artifact.

PREDICTED FAILURE
All 15 parametrised cases of `test_normalize_host_token_returns_pinned_value` fail at line 53
with AttributeError on `moderation.normalize_host_token`, because `engine/server/data/moderation.py`
does not define it. `test_fixture_holds_exactly_the_pinned_pairs` fails at line 46 with
FileNotFoundError on `FIXTURE.read_text`, because `tests/active/host_tokens.json` does not exist yet.

NOT ASSESSED
1. `code_under_test` lists `tests/active/host_tokens.json` and `tests/active/test_host_normalisation.py`
   as NEW. Neither exists yet, so I could not read them. Line 48 was assessed from the test's
   side only.
2. `fixtures_path` was not supplied. The test uses no pytest fixtures other than `parametrize`.
   The only conftest found (`tests/active/conftest.py`) does not cover `tests/tmp/`, so I did not read it.
```

Notes on the passes behind the verdict (not part of the gate record):

- **Anti-patterns:**
  - None of the grep entries apply (`doc-lint-grep`, `section-scoped-substring-grep`, `whole-file-source-name-grep`): no `.md` file is read.
  - Not `tautological-assertion`: every expected value is an independent literal (lines 26–40), not computed.
  - Not `echoed-literal`: the value passes through the production `normalize_host_token` at line 53.
  - Not `single-value-pin`: 15 inputs, most of which are not fixed points (`" Tube.Example "` → `"tube.example"`), so identity fails.
  - Not `absence-only-assertion`: the four `None` cases (lines 36–39) sit beside eleven positive cases.
- **Ladder:** line 53 calls the function directly and checks its return value (rung 1), which is the highest rung and fits a pure function. Line 48 is rung 4, matched to a structured JSON artifact. Nothing lands on the anti-rung, and there is no downshift.
- **Stub question:** the test would catch each plausible wrong implementation:

  | Wrong implementation | Cases that fail |
  |---|---|
  | Hard-coded `"tube.example"` | The `None` cases, `"tube.example:9000"`, `"[::1]"` and the punycode case |
  | `return None` | The 11 positive cases |
  | Identity | Line 26 |
  | Stripping every trailing dot | Line 40 (`"https://tube.example./"` → `"tube.example."`) |

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (9 clauses: 2 must_prove, 5 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `normalize_host_token` returns each fixture pair's expected value | :53, with :47 and :48 | :53 excludes a port that gets any of the 11 non-null pinned pairs wrong (e.g. keeps `:8080`, drops `:9000`, leaves `Bücher` un-punycoded, strips the dot in `tube.example./`). :47 and :48 exclude a fixture holding pairs other than those checked, so "each fixture pair" is covered too | CARRIED |
| C1b | must_prove | None where the expected value is null | :53 (cases `''`, `'   '`, `'.'`, `'https://'`) | a port returning `""`, `"."` or the raw input instead of None. `==` against None does not accept `""` | CARRIED |
| D1 | docstring | "the Engine's port of the crawler's `normalizeHostToken`" | :53 | a port that differs from the crawler on any pinned value (the pinned WHATWG values stand in for the crawler; the crawler itself is not run) | CARRIED |
| D2 | docstring | fixture "holds exactly the 15 input -> expected pairs pinned by the requirements" | :47, :48 | a fixture with a missing, extra, duplicated or altered pair. :47 catches the duplicate that the dict at :48 would collapse | CARRIED |
| D3 | docstring | "WHATWG `URL.hostname` values, null for None" | :48 | a fixture that writes `""` or `"null"` in place of JSON null, or non-WHATWG values | CARRIED |
| D4 | docstring | "cannot drift to match the port" | :48 against the hard-coded `PINNED` at :25-41 | a fixture edited to fit the port's output. `PINNED` is written independently of the fixture | CARRIED |
| D5 | docstring | "for every pinned pair … returns the expected value, and None where it is null" | :53 (parametrised over all 15) | as C1a and C1b | CARRIED |
| N1 | name | `test_fixture_holds_exactly_the_pinned_pairs` | :47, :48 | as D2 | CARRIED |
| N2 | name | `test_normalize_host_token_returns_pinned_value` | :53 | as C1a | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase1.py:25
   The pinned set covers empty, whitespace-only, `.`, and a scheme with no host. It has no malformed URL that the parser rejects (for example `http://[`, where `urlparse` raises `ValueError`, the error the existing `normalize_host` at moderation.py:50-53 catches). It also has no `None` input, which the sibling `normalize_host` accepts (moderation.py:39-42). These cases are outside C1's pinned pairs, so this does not block.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists `tests/active/host_tokens.json` and `tests/active/test_host_normalisation.py`, but neither exists in the worktree. The fixture's contents could not be read, so D2 and D3 were judged only from what :47 and :48 would enforce. The test does not reference `test_host_normalisation.py`, and that file was not assessed.
2. `normalize_host_token` is not yet defined in `engine/server/data/moderation.py` (the only similar function is `normalize_host` at :39). Its accepted input types and failure behaviour could not be read from code. Bounds were judged from the pinned table and the sibling function.

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`engine/server/data/moderation.py` gains `normalize_host_token`, placed directly after the unchanged `normalize_host`, and it returns the pinned value for every pair in `tests/active/host_tokens.json`.

- C1 - `normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null.

must_prove:
- C1 - `normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null.

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - resumed

`tests/tmp/test_10_normalise_instance_hosts_phase1.py` matches the bytes banked when its red was confirmed, so the gate it already passed stands and it was not re-authored.

## 2026-09-26 - Step 7 - Phase 1 (Python port of normalizeHostToken) - checkpoint outcome (run 1)

`tests/tmp/test_10_normalise_instance_hosts_phase1.py` exited 0 after the phase landed.

<changes>
Nothing needed writing this turn. All three files in this phase were already in the worktree when the turn started. I checked each against the crawler source and the checkpoint's pinned values, and left them unchanged. I did not write them in this turn, so they came from an earlier pass over this step.

### `engine/server/data/moderation.py`
- `normalize_host_token(value: str) -> str | None` sits directly after `normalize_host`, which is unchanged. It is a line-for-line port of `normalizeHostToken` in `engine/crawler/src/host-filters.ts`:
  - strips and lowercases the input, and returns None if nothing is left;
  - sends `http://` / `https://` inputs through `_whatwg_hostname`;
  - sends inputs containing `/` through `_whatwg_hostname` as `https://{raw}`;
  - otherwise strips leading and trailing dots, returning None if nothing is left;
  - catches a single `ValueError`, which stands in for the crawler's try/catch around the whole body.
- `_whatwg_hostname(url)` is a private helper that returns the hostname WHATWG `URL.hostname` would give:
  - reads `urlparse(...).port` so a bad port raises, as WHATWG does;
  - returns None for an empty host;
  - puts brackets around the compressed form of IPv6 literals;
  - IDNA-encodes only non-ASCII hosts.
  - It carries a `rat-tail:` comment: `urlparse` accepts forbidden host code points that WHATWG rejects, so the two only match on the pinned inputs. The fix is a forbidden-code-point check in this helper once a fixture input exposes the gap.
- The module header comment names both normalisers and what each is for.
- New imports: `ipaddress` and `urlparse`. New module constant: `URL_SCHEME_PREFIXES`.

### `tests/active/host_tokens.json`
- Contains exactly the 15 `{"input", "expected"}` pairs from the requirements, with `null` meaning None. I compared them one by one against the checkpoint's `PINNED` dict and they match.

### `tests/active/test_host_normalisation.py`
- A durable test, parametrised over every pair in `host_tokens.json`, that asserts `normalize_host_token(input) == expected`. It gets `ROOT` from `tests/active/conftest.py`, which I confirmed exports it.

### What I ran
- I wrote a probe, `tests/tmp/probe_host_token.py`, that runs all 15 fixture pairs through `normalize_host_token` and asserts none of them mismatch. It passed (exit 0). I did not run the gating checkpoint myself.
- I have no delete tool, so the probe is still in the tree. The operator can remove it with `rm tests/tmp/probe_host_token.py`; it gates nothing.
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
  tests/tmp/test_10_normalise_instance_hosts_phase1.py  16 passed                              0.0s
  ----------------------------------------------------
  total                                                 16 passed                              0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`test_host_normalisation.py` checks the crawler's compiled `normalizeHostToken` against the same pinned fixture, and the check cannot pass without node and a current `dist/host-filters.js`.

- C1 - `dist/host-filters.js` run under node returns each fixture pair's expected value.
- C2 - A missing node, a missing dist or a stale dist makes the crawler test fail rather than skip.

must_prove:
- C1 - `dist/host-filters.js` run under node returns each fixture pair's expected value.
- C2 - A missing node, a missing dist or a stale dist makes the crawler test fail rather than skip.

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - self-check (audit round 1, send-back 0)

`tests/tmp/test_10_normalise_instance_hosts_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:154 — `pytest tests/active/test_host_normalisation.py -k crawler_dist` runs in its own process on this tree and its junit outcome is "passed" - expected: "passed". The harness run's correct variant showed this: probe_phase2_harness.py `test_durable_crawler_test_passes_on_this_tree[correct]` PASSED. Today the outcome is "not collected": the run printed `assert 'not collected' == 'passed'` at line 154. - excludes: An mtime-only staleness rule. This tree's dist is committed with src but is a few ms older on disk, so that rule fails the durable test. Observed in the harness: `[mtime_only]` FAILED with `AssertionError: Failed: older; run: cd engine/crawler && npm install && npm run build / assert 'failure' == 'passed'`. With no durable test at all (today's tree), it reads "not collected".
- C1 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:165-166 — setup: a dist that is current by git (committed after src) but has `.toLowerCase()` removed, so only " Tube.Example " comes out wrong. Asserted: the durable test's outcome is "failure", and junit's message attribute contains 'Tube.Example' - expected: "failure", with 'Tube.Example' in the junit message. Observed: the harness's `test_durable_crawler_test_fails_on_current_dist_with_one_wrong_value[correct]` PASSED, now reading only the message attribute. Today: `assert 'not collected' == 'failure'` at line 165. - excludes: A durable test that runs node and checks only its returncode, never comparing the output to the fixture. It reports "passed" here. Observed: harness `[no_compare]` FAILED with `assert 'passed' == 'failure'` at line 165.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:173-174 — with a PATH holding only git (no node), the durable test's outcome is "failure", and junit's message contains "cd engine/crawler && npm install && npm run build" - expected: "failure", with the build hint in the message. Observed: harness `test_durable_crawler_test_fails_loudly_without_node[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 173. - excludes: `pytest.skip` when node is missing. Observed: harness `[skip]` FAILED with `AssertionError: no node / assert 'skipped' == 'failure'` at line 173.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:179-180 — with DIST redirected to a missing path, the outcome is "failure" and junit's message (not the traceback text) contains the build hint - expected: "failure", with the build hint in the message. Observed: harness `test_durable_crawler_test_fails_loudly_when_dist_is_missing[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 179. - excludes: No dist-existence check, with the hint text written literally in the test's source. The durable test then fails on git or node, not with the hint. Observed: harness `[no_dist_check]` FAILED at line 180 with `assert 'cd engine/crawler && npm install && npm run build' in "subprocess.CalledProcessError: Command '['/usr/bin/git', 'log', ...]' returned non-zero exit status 128."`. Before this rewrite the same variant PASSED (`-k "no_dist_check and dist_is_missing"`: 1 passed), because the traceback text listed the literal.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:190-191 — setup: src committed after dist (2021 vs 2020), but dist newer on disk. Asserted: outcome "failure" with the build hint in the message - expected: "failure", with the hint. Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 190. - excludes: An mtime-only rule sees dist as newer and passes. Observed: harness `[mtime_only]` FAILED with `assert 'passed' == 'failure'` at line 190.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:200 — with dist committed after src but older on disk, the outcome is "passed". This is the positive side of the staleness rule: commit time wins for committed files - expected: "passed". Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'passed'` at line 200. - excludes: An mtime-only rule, or one that is always stale. Observed: harness `[mtime_only]` FAILED with `Failed: older; run: ... / assert 'failure' == 'passed'` at line 200.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:211-212 — setup: equal commit times, an uncommitted src edit, and dist older on disk. Asserted: outcome "failure" with the build hint in the message - expected: "failure", with the hint. Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 211. - excludes: A git-only rule that ignores a dirty src. Observed: harness `[git_only]` FAILED with `assert 'passed' == 'failure'` at line 211.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:220-221 — with dist never committed (no history) and older on disk than src, the outcome is "failure" with the build hint - expected: "failure", with the hint. Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 220. - excludes: A git-only rule that treats missing history as current. Observed: harness `[git_only]` FAILED with `assert 'passed' == 'failure'` at line 220.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase2.py:227-228 — with a PATH holding only node (no git) on this tree, the outcome is "failure" and junit's message names git - expected: "failure", with a message such as "Failed: git is not on PATH, so the freshness of dist/host-filters.js cannot be checked; run: ...". Observed: harness `[correct]` PASSED. Today: `assert 'not collected' == 'failure'` at line 227. - excludes: An mtime-only rule never needs git and fails for the wrong reason, the checkout's mtime order. Observed: harness `[mtime_only]` FAILED at line 228 with `assert 'git' in 'Failed: older; run: cd engine/crawler && npm install && npm run build'`. A rule that treats a missing git as current would report "passed" at line 227.

<assertions>
tests/tmp/test_10_normalise_instance_hosts_phase2.py:142 - node, importing the real `engine/crawler/dist/host-filters.js` by file:// URL through HOST_FILTERS_URL, exits with returncode 0 - C1
tests/tmp/test_10_normalise_instance_hosts_phase2.py:143 - dict(zip(inputs, node output)) equals the 15-pair PINNED map, written out independently of the fixture and of the crawler - C1
tests/tmp/test_10_normalise_instance_hosts_phase2.py:149 - on this tree, `pytest tests/active/test_host_normalisation.py -k crawler_dist` in its own process reports passed (junit). Here dist is committed in the same second as src but is 2 ms older on disk, so an mtime-only rule goes red. - C1
tests/tmp/test_10_normalise_instance_hosts_phase2.py:160 - with a dist that is current by git (committed after src) but has `.toLowerCase()` removed, the durable test reports failure - C1
tests/tmp/test_10_normalise_instance_hosts_phase2.py:161 - that failure's message shows the wrong value 'Tube.Example', so the durable test compared node's output against the fixture - C1
tests/tmp/test_10_normalise_instance_hosts_phase2.py:162 - that failure's message does not carry the build hint (a current dist is not reported as stale) - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:168 - with a PATH holding only git (no node), the durable test reports failure, not skipped or error - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:169 - that failure message contains "cd engine/crawler && npm install && npm run build" - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:174 - with DIST pointed at a missing path, the durable test reports failure - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:175 - that failure message contains the build hint - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:185 - with src committed after dist (2021 vs 2020) but dist newer on disk, the durable test reports failure, which only the commit-time rule can produce - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:186 - that failure message contains the build hint - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:195 - with dist committed after src but older on disk, the durable test reports passed, so commit time wins over mtime for committed files - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:206 - with equal commit times, an uncommitted src edit and dist older on disk, the durable test reports failure (the mtime fallback for a dirty src) - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:207 - that failure message contains the build hint - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:215 - with dist never committed (no history) and older on disk than src, the durable test reports failure (the mtime fallback for no history) - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:216 - that failure message contains the build hint - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:222 - with a PATH holding only node (no git), on this otherwise current tree, the durable test reports failure, not skipped - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:223 - that failure message names git - C2
tests/tmp/test_10_normalise_instance_hosts_phase2.py:86 - control used by every run: the junit report holds exactly one testcase and its name contains crawler_dist, so an empty -k selection (today's phase-1 file) cannot count as an outcome - C1, C2
</assertions>

<probes>
1. tests/tmp/probe_phase2_env.py, run with ValidateTests ["tests/tmp/probe_phase2_env.py", "-s"], output read from tests/last_test_output.txt:
- Binaries: python 3.14.7 (pixi); node v22.22.2 at /run/user/1000/fnm_multishells/.../bin/node (realpath ~/.local/share/fnm/node-versions/v22.22.2/installation/bin/node); git at /usr/bin/git.
- Real tree history: `git log -1 --format=%ct` gives 1790369883 for both src/host-filters.ts and dist/host-filters.js. `git status --porcelain` on both is empty.
- Real tree mtimes: src 1790462159.2715, dist 1790462159.2698, so dist is older on disk.
- tests/tmp is not gitignored.
- node on the real dist with the probe's NODE_SCRIPT exited 0 and printed ["tube.example","tube.example","tube.example","tube.example","tube.example","tube.example","tube.example","tube.example:9000","[::1]","xn--bcher-kva.example",null,null,null,null,"tube.example."]. Zipped with the inputs, that equals PINNED.
- git redirection: with GIT_DIR/GIT_WORK_TREE set to a temp repo and cwd = the real worktree root, `git log -1 --format=%ct -- <abs path>` gave the fixed commit dates (1609459200 / 1577836800). An untracked file gave empty output. `git status --porcelain` gave '' when clean, ' M src/a.ts' after an edit, and '?? src/new.ts' for an untracked file.
2. Grep of validate_tests.py: the gating run passes junit as an argument (`--junit-xml={junit}`, line 1994), not via PYTEST_ADDOPTS, so the nested pytest runs cannot overwrite its report. No pytest config was found (grep for pytest/addopts in pyproject.toml matched nothing).
3. Harness check: tests/tmp/probe_durable_host.py is a copy of the plan's durable crawler test with a PROBE_VARIANT switch. tests/tmp/probe_phase2_harness.py imports the checkpoint's tests with DURABLE pointed at that copy and runs them across 5 variants. Command: ValidateTests ["tests/tmp/probe_phase2_harness.py", "-rA"]. Result: 42 passed, 8 failed.
- correct: all 10 passed.
- skip (pytest.skip on missing node): fails_loudly_without_node went red.
- mtime_only: passes_on_this_tree, fails_loudly_when_src_committed_after_dist, passes_when_dist_committed_after_src_though_older_on_disk and fails_without_git went red.
- git_only (ignores a dirty src, treats no history as current): fails_loudly_when_uncommitted_src_edit_is_newer_than_dist and fails_loudly_when_dist_has_no_history_and_is_older went red.
- no_compare (never compares node output): fails_on_current_dist_with_one_wrong_value went red.
- The correct variant passing that test confirms the junit failure text carries 'Tube.Example'.
Predicted, not observed: I did not run the gating checkpoint itself against today's phase-1 tests/active/test_host_normalisation.py. Its red there rests on the line-86 control: -k crawler_dist selects no test, so the junit holds 0 testcases. The workflow's run will confirm this.
I have no delete tool, so these probe files remain for the operator to remove; none matches test_*.py: tests/tmp/probe_phase2_env.py, tests/tmp/probe_durable_host.py, tests/tmp/probe_phase2_harness.py.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_10_normalise_instance_hosts_phase2.py` - 10858 characters, inlined in full

```
"""Phase 2 checkpoint: the crawler's compiled `normalizeHostToken` against the pinned pairs, and the durable test that checks it failing loudly when it cannot.

- `engine/crawler/dist/host-filters.js`, imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values, so with phase 1 the Python port equals the crawler on the fixture.
- `tests/active/test_host_normalisation.py -k crawler_dist`, run in its own pytest, passes on this tree, whose dist is committed with src but is older on disk, and fails on a dist that is current but returns a wrong value for one input.
- That run fails, never skips, with the build hint in its message when node is off PATH, when dist is missing, when src was committed after dist, when src has an uncommitted edit newer on disk than dist, and when dist has no history and is older on disk than src; it fails when git is off PATH; and it passes when dist was committed after src though older on disk.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DURABLE = ROOT / "tests" / "active" / "test_host_normalisation.py"
REAL_SRC = ROOT / "engine" / "crawler" / "src" / "host-filters.ts"
REAL_DIST = ROOT / "engine" / "crawler" / "dist" / "host-filters.js"
BUILD_HINT = "cd engine/crawler && npm install && npm run build"
NODE = shutil.which("node")
GIT = shutil.which("git")

# The pinned values from the requirements, written out independently of the fixture and of the crawler.
PINNED = {
    " Tube.Example ": "tube.example",
    "tube.example.": "tube.example",
    "..tube.example..": "tube.example",
    "https://Tube.Example/": "tube.example",
    "http://tube.example:8080/path": "tube.example",
    "https://user@tube.example": "tube.example",
    "tube.example/videos": "tube.example",
    "tube.example:9000": "tube.example:9000",
    "https://[::1]:8080/": "[::1]",
    "https://bücher.example/": "xn--bcher-kva.example",
    "": None,
    "   ": None,
    ".": None,
    "https://": None,
    "https://tube.example./": "tube.example.",
}

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);
const inputs = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));
"""

# Loaded into the durable test's own pytest: points its SRC/DIST constants at a scenario's files, and errors (not fails) if a constant is gone, so a rename cannot pass as a loud failure.
PATHS_PLUGIN = """
import json
import os
from pathlib import Path


def pytest_runtest_setup(item):
    for name, value in json.loads(os.environ["HOST_FILTERS_PATHS"]).items():
        if not isinstance(getattr(item.module, name, None), Path):
            raise RuntimeError(f"{item.module.__name__} has no Path constant {name} to redirect")
        setattr(item.module, name, Path(value))
"""

# The one line whose removal makes a single pinned input (" Tube.Example ") come out wrong.
LOWERCASE_LINE = "const raw = value.trim().toLowerCase();"


def _run_crawler_test(tmp_path: Path, env: dict[str, str] | None = None, paths: dict[str, Path] | None = None) -> tuple[str, str]:
    """Run the durable crawler test in its own pytest; return its junit outcome (passed, failure, error or skipped) and message."""
    report = tmp_path / "report.xml"
    cmd = [sys.executable, "-m", "pytest", str(DURABLE), "-k", "crawler_dist", "-p", "no:cacheprovider", f"--junit-xml={report}"]
    run_env = {**os.environ, **(env or {})}
    if paths:
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "host_paths_plugin.py").write_text(PATHS_PLUGIN, encoding="utf-8")
        run_env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(plugin_dir), os.environ.get("PYTHONPATH")]))
        run_env["HOST_FILTERS_PATHS"] = json.dumps({name: str(path) for name, path in paths.items()})
        cmd += ["-p", "host_paths_plugin"]
    proc = subprocess.run(cmd, cwd=ROOT, env=run_env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    output = proc.stdout[-4000:] + proc.stderr[-2000:]
    cases = list(ET.parse(report).getroot().iter("testcase")) if report.is_file() else []
    # Control: exactly the durable crawler test ran, so the outcome below is its outcome and not an empty selection's.
    assert len(cases) == 1 and "crawler_dist" in cases[0].get("name", ""), output
    for tag in ("failure", "error", "skipped"):
        found = cases[0].find(tag)
        if found is not None:
            return tag, f"{found.get('message', '')}\n{found.text or ''}"
    return "passed", output


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
    subprocess.run([GIT, "-c", "user.name=checkpoint", "-c", "user.email=checkpoint@example.invalid", "-c", "commit.gpgsign=false", *args], cwd=repo, env=env, capture_output=True, check=True)


def _commit(repo: Path, path: Path, date: str) -> None:
    _git(repo, "add", str(path.relative_to(repo)))
    _git(repo, "commit", "-q", "-m", path.name, date=date)


def _crawler_copy(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A throwaway git repo holding copies of the crawler's src and dist, nothing committed yet."""
    assert GIT is not None and NODE is not None
    repo = tmp_path / "crawler"
    src = repo / "src" / "host-filters.ts"
    dist = repo / "dist" / "host-filters.js"
    src.parent.mkdir(parents=True)
    dist.parent.mkdir()
    shutil.copyfile(REAL_SRC, src)
    shutil.copyfile(REAL_DIST, dist)
    # The crawler package's "type": "module" is what makes node load dist/*.js as ESM; the copy needs the same.
    (repo / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    _git(repo, "init", "-q")
    return repo, src, dist


def _older_on_disk(older: Path, newer: Path) -> None:
    now = time.time()
    os.utime(older, (now - 3600, now - 3600))
    os.utime(newer, (now, now))


def _git_env(repo: Path) -> dict[str, str]:
    # The durable test runs git from the real worktree root; these make that git answer for the scenario's repo instead.
    return {"GIT_DIR": str(repo / ".git"), "GIT_WORK_TREE": str(repo)}


def _path_with_only(tmp_path: Path, name: str, target: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / name).symlink_to(os.path.realpath(target))
    return str(bin_dir)


def test_crawler_dist_under_node_returns_pinned_values():
    assert NODE is not None
    inputs = list(PINNED)
    proc = subprocess.run([NODE, "--input-type=module", "-e", NODE_SCRIPT], input=json.dumps(inputs), capture_output=True, text=True, encoding="utf-8", timeout=60, env={**os.environ, "HOST_FILTERS_URL": REAL_DIST.as_uri()})
    assert proc.returncode == 0, proc.stderr  # C1
    assert dict(zip(inputs, json.loads(proc.stdout))) == PINNED  # C1


def test_durable_crawler_test_passes_on_this_tree(tmp_path):
    # This tree's dist is committed with src yet a few ms older on disk, as a checkout leaves it: an mtime-only rule fails here.
    outcome, message = _run_crawler_test(tmp_path)
    assert outcome == "passed", message  # C1


def test_durable_crawler_test_fails_on_current_dist_with_one_wrong_value(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    text = dist.read_text(encoding="utf-8")
    assert text.count(LOWERCASE_LINE) == 1
    dist.write_text(text.replace(LOWERCASE_LINE, "const raw = value.trim();"), encoding="utf-8")
    _commit(repo, src, "2020-01-01T00:00:00Z")
    _commit(repo, dist, "2021-01-01T00:00:00Z")
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C1
    assert "'Tube.Example'" in message  # C1
    assert BUILD_HINT not in message  # C2


def test_durable_crawler_test_fails_loudly_without_node(tmp_path):
    assert GIT is not None
    outcome, message = _run_crawler_test(tmp_path, env={"PATH": _path_with_only(tmp_path, "git", GIT)})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_loudly_when_dist_is_missing(tmp_path):
    outcome, message = _run_crawler_test(tmp_path, paths={"DIST": tmp_path / "dist" / "host-filters.js"})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_loudly_when_src_committed_after_dist(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, dist, "2020-01-01T00:00:00Z")
    _commit(repo, src, "2021-01-01T00:00:00Z")
    # Newer on disk, so only the commit-time rule can call this dist stale.
    _older_on_disk(src, dist)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_passes_when_dist_committed_after_src_though_older_on_disk(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, src, "2020-01-01T00:00:00Z")
    _commit(repo, dist, "2021-01-01T00:00:00Z")
    _older_on_disk(dist, src)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "passed", message  # C2


def test_durable_crawler_test_fails_loudly_when_uncommitted_src_edit_is_newer_than_dist(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, dist, "2020-01-01T00:00:00Z")
    _commit(repo, src, "2020-01-01T00:00:00Z")
    # Equal commit times: only the uncommitted edit, judged by mtime, can call this dist stale.
    src.write_text(src.read_text(encoding="utf-8") + "// edited, not rebuilt\n", encoding="utf-8")
    _older_on_disk(dist, src)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_loudly_when_dist_has_no_history_and_is_older(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, src, "2020-01-01T00:00:00Z")
    _older_on_disk(dist, src)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_without_git(tmp_path):
    assert NODE is not None
    outcome, message = _run_crawler_test(tmp_path, env={"PATH": _path_with_only(tmp_path, "node", NODE)})
    assert outcome == "failure", message  # C2
    assert "git" in message  # C2

```


Gate: satisfied

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - red (audit round 1)

`tests/tmp/test_10_normalise_instance_hosts_phase2.py` exited 1.

```
  tests/tmp/test_10_normalise_instance_hosts_phase2.py  9 failed, 1 passed                     0.0s
  ----------------------------------------------------
  total                                                 9 failed, 1 passed                     1.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 3 UNCARRIED clause(s) - C1b, D2, D4; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this (rules/shape.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:228
   assert "git" in message  # C2
   The test's other failure checks look for the exact BUILD_HINT string. This one only looks
   for the three letters "git" anywhere in junit's message. It still separates a durable test
   that never calls git, because that test comes out "passed" and line 227 turns red. But any
   failure whose message happens to include "git" in a path or another word also passes.
   Matching the durable test's own git-missing wording would pin it the way lines 174/180 pin
   BUILD_HINT. No <anti_pattern> entry names this, so it is a Recommendation only.

PREDICTED FAILURE
Fails at line 154 in test_durable_crawler_test_passes_on_this_tree: `outcome == "passed"` gets
"not collected", because tests/active/test_host_normalisation.py has no test matching
`-k crawler_dist` yet. Lines 165, 173, 179, 190, 200, 211, 220 and 227 fail the same way on
their outcome assertion. Line 148 (the premise test) is expected to pass as things stand.

NOT ASSESSED
1. `fixtures_path` was "none found". The durable file imports ROOT from `conftest`, which was
   not read. The stub question does not depend on it, because the checkpoint only sees the
   durable test through junit outcome and message.
2. Whether node and git are on PATH in the environment that will run this could not be checked
   by reading. The prediction for line 148 assumes both are present. engine/crawler/dist/host-filters.js
   was confirmed to exist, and it contains LOWERCASE_LINE exactly once, which the line-160
   precondition needs.

Anti-patterns pass: none of the anti-pattern entries applies. No .md file is read.
PINNED (line 27) holds hand-written expected values set against node's output, not a mirror of
a code constant, and nothing in the test works them out again. The negative at line 167 is
paired with positive checks at lines 165–166. The wrong-value scenario (157) and the
this-tree pass (151) read the same observable at two inputs, so there is no single-value pin.

Ladder pass: rung 2 (node subprocess, and pytest run as a subprocess) with a junit XML parse.
That is the highest rung available: the JS function has no Python entry point, and "fails
rather than skips" can only be observed from outside the durable test's own pytest run. No
downshift, so no comment is required.

Stub question: this file does not pass against a stub durable test. With no test present it
gets "not collected". A test that always fails is caught at 154/200. A test that always calls
pytest.fail(BUILD_HINT) is caught at 154. One that only checks presence without comparing
values is caught at 165–166. One that goes by mtime alone is caught at 154 (this tree) and
190. One that goes by commit time alone is caught at 211 and 220. One that skips gets
"skipped" and is caught at every `outcome ==` line.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (29 clauses: 7 must_prove, 12 docstring, 10 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "`dist/host-filters.js` run under node returns" the expected value for every pinned input | :148 | a dist that gets any one of the 15 inputs wrong or leaves one out (compares the whole dict; `zip` truncation would lose a key and break equality) | CARRIED |
| C1b | must_prove | the crawler test holds dist to "each fixture pair" | :154, :165, :166 | a crawler test that never runs dist, skips, or compares only the Python port. It does not exclude a crawler test that checks a subset of pairs: the one mutation breaks only `" Tube.Example "` | UNCARRIED |
| C2a | must_prove | "a missing node" makes the crawler test fail rather than skip | :173, :174 | a skip, an error, no test collected, or a failure without the build hint when node is off PATH. :154 is the node-present contrast | CARRIED |
| C2b | must_prove | "a missing dist" fails rather than skips | :179, :180 | a skip, error or silent pass when DIST does not exist | CARRIED |
| C2c1 | must_prove | "a stale dist" (src committed after dist) fails | :190, :191 | a check that only compares mtimes, since dist is newer on disk here (:188), and a skip | CARRIED |
| C2c2 | must_prove | "a stale dist" (uncommitted src edit newer on disk) fails | :211, :212 | a check that only compares commit times, since the commit times are equal (:206) | CARRIED |
| C2c3 | must_prove | "a stale dist" (dist has no history and is older on disk) fails | :220, :221 | a check that skips or passes when git has no commit time for dist | CARRIED |
| D1 | docstring | "imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values" | :146, :148 | a dist that differs on any pinned input | CARRIED |
| D2 | docstring | "so with phase 1 the Python port equals the crawler on the fixture" | none | nothing: `PINNED` is a hand copy, and no assertion ties it to `tests/active/host_tokens.json` | UNCARRIED |
| D3 | docstring | "passes on this tree" | :154 | a skipping, erroring or missing crawler test ("not collected" ≠ "passed") | CARRIED |
| D4 | docstring | "whose dist is committed with src but is older on disk" | none | a premise the test never checks: nothing asserts the tree's commit or mtime state | UNCARRIED |
| D5 | docstring | "fails on a dist that is current but returns a wrong value for one input" | :160, :165, :166, :167 | a crawler test that does not compare dist's output, or that reports this as staleness (:167) | CARRIED |
| D6 | docstring | fails, never skips, with the build hint "when node is off PATH" | :173, :174 | a skip, or a failure without the hint | CARRIED |
| D7 | docstring | "... when dist is missing" | :179, :180 | same, for a missing dist | CARRIED |
| D8 | docstring | "... when src was committed after dist" | :190, :191 | a check that only compares mtimes | CARRIED |
| D9 | docstring | "... when src has an uncommitted edit newer on disk than dist" | :211, :212 | a check that only compares commit times | CARRIED |
| D10 | docstring | "... when dist has no history and is older on disk than src" | :220, :221 | a skip or pass when dist has no commit history | CARRIED |
| D11 | docstring | "it fails when git is off PATH" | :227 | a skip or pass without git | CARRIED |
| D12 | docstring | "passes when dist was committed after src though older on disk" | :200 | a crawler test that always fails, or one that only compares mtimes | CARRIED |
| N1 | name | `test_crawler_dist_under_node_returns_pinned_values` | :148 | a dist with any wrong pinned value | CARRIED |
| N2 | name | `test_durable_crawler_test_passes_on_this_tree` | :154 | a skipping or missing crawler test | CARRIED |
| N3 | name | `..._fails_on_current_dist_with_one_wrong_value` | :165, :166 | a crawler test that does not compare values | CARRIED |
| N4 | name | `..._fails_loudly_without_node` | :173, :174 | a skip, or a failure with no hint | CARRIED |
| N5 | name | `..._fails_loudly_when_dist_is_missing` | :179, :180 | same | CARRIED |
| N6 | name | `..._fails_loudly_when_src_committed_after_dist` | :190, :191 | a check that only compares mtimes | CARRIED |
| N7 | name | `..._passes_when_dist_committed_after_src_though_older_on_disk` | :200 | a check that always fails or only compares mtimes | CARRIED |
| N8 | name | `..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist` | :211, :212 | a check that only compares commit times | CARRIED |
| N9 | name | `..._fails_loudly_when_dist_has_no_history_and_is_older` | :220, :221 | a skip or pass with no history | CARRIED |
| N10 | name | `..._fails_without_git` | :227 | a skip or pass without git | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:161, :165–166
   `dist.write_text(text.replace(LOWERCASE_LINE, "const raw = value.trim();"), encoding="utf-8")`
   `assert "'Tube.Example'" in message  # C1`
   C1 says the crawler test holds dist to *each* fixture pair's expected value. The checkpoint shows this through the crawler test only twice: it passes on the real dist (:154), and it fails when one line is mutated. That mutation breaks exactly one of the 15 pairs (`" Tube.Example "`), as the comment at :66 says. So a crawler test that checks only that input, or any subset containing it, passes :154, :165 and :166 alike. This is the "X per Y needs a second Y" case in `<whole-claim>`: one wrong pair proves the test compares values, not that it compares every pair. :148 checks every pinned value, but it checks them against the real dist directly, not through the code under test. Its own comment at :143 calls it a "Premise, true before the phase", so it cannot carry the crawler test's coverage.

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:26–43
   D2 is UNCARRIED. The docstring says "the Python port equals the crawler on the fixture", but `PINNED` is written out "independently of the fixture" and never compared with `tests/active/host_tokens.json`. The two match on disk today, but nothing here would notice if they drifted apart.
2. whole-claim (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:152–154
   D4 is UNCARRIED. "whose dist is committed with src but is older on disk" describes the real tree, and nothing asserts it. If the tree's state changes, :154 still passes and no longer tests what the docstring says.
3. bounds (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:151–154
   The equal-commit-time, no-uncommitted-edit, dist-older-on-disk boundary is only reached through the real tree, whose state is unasserted (D4). No scenario in a controlled repo, like the ones built at :194–221, pins it.

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. `tests/active/conftest.py` was read because the code under test imports `ROOT` from it, and it has no effect on this test's claims.

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - self-check (audit round 2, send-back 0)

`tests/tmp/test_10_normalise_instance_hosts_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_10_normalise_instance_hosts_phase2.py:160 — node running the real dist returns exactly PINNED for all 15 inputs. :163 — the fixture's pairs are exactly PINNED. :169 — the durable crawler test reports passed on this tree. :184/:185 — for each of the 15 fixture inputs in turn, with a current dist wrong on that input alone (control :180), the durable test reports failure and the message contains `wrong-host.invalid`. :197/:198 — with the realistic `.toLowerCase()` removal, it fails naming 'Tube.Example'. - expected: :160 and :163 equality holds. :169 "passed". :184 "failure" and :185 true for every one of the 15 parametrized inputs. :197 "failure" with 'Tube.Example' in the message. - excludes: A durable crawler test that compares only some fixture pairs (observed with the `subset` variant, which drops the last pair): :184 reads "passed" for `'https://tube.example./'`. One that never compares dist's output (`no_compare`): :184 reads "passed" for all 15. One that skips or does not exist: :169 reads "skipped"/"not collected". A fixture that has drifted from the requirements: :163 goes red.
- C2 - test_10_normalise_instance_hosts_phase2.py:205/:206 (no node), :211/:212 (missing dist), :222/:223 (src committed after dist, dist newer on disk), :253/:254 (uncommitted src edit, equal commit times), :262/:263 (dist has no history and is older): each asserts outcome == "failure" and the build hint in the junit message. :269 fails without git. Contrasts: :232 and :242 assert "passed" when dist was committed after src, or at the same time as a clean src, though older on disk. :186 and :199 assert that a current-but-wrong dist is not reported as stale. - expected: "failure" with BUILD_HINT in the message in each stale, missing or no-node scenario. "passed" at :232 and :242. No BUILD_HINT at :186 and :199. - excludes: pytest.skip on a missing node: :205 reads "skipped". Mtime-only staleness: :222 reads "passed", and :232 and :242 read "failure". Commit-time-only staleness: :253 and :262 read "passed". A >= commit-time rule: :242 reads "failure". A test that always fails with the hint: :169 and :232 read "failure".

<items>
<item id="C1b">
<disposition>fixed</disposition>
<what>New `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input`, parametrized over all 15 inputs in `tests/active/host_tokens.json`. For each input it renames dist's `normalizeHostToken` to `pinnedNormalizeHostToken` and appends a wrapper export that returns `wrong-host.invalid` for that one input and passes every other input through. A control at :180 checks under node that this dist differs from PINNED on that input and nowhere else. The dist is committed after src, so it is current. Then :184 (`outcome == "failure"`) and :185 (`WRONG_HOST in message`) require the durable test to fail on the wrong value, and :186 requires that failure not to be reported as staleness. A durable test that leaves out any one fixture pair passes the run for that pair and turns it red. Observed in the harness: a `subset` variant that drops the last pair failed only at `['https://tube.example./']`, and the correct variant passed all 15.</what>
</item>
<item id="D2">
<disposition>fixed</disposition>
<what>The premise test now asserts that the fixture is PINNED. :162 checks `len(FIXTURE_PAIRS) == len(PINNED)`, so a duplicated input cannot hide inside a dict, and :163 checks `{pair["input"]: pair["expected"] for pair in FIXTURE_PAIRS} == PINNED`. The docstring now says this outright ("`tests/active/host_tokens.json` holds exactly those 15 pairs"). If the fixture drifts from the hand-written requirement values, the test goes red, and the chain "Python port equals fixture equals PINNED equals dist" is now checked at every link.</what>
</item>
<item id="D4">
<disposition>fixed</disposition>
<what>I removed the unasserted description of the real tree's state from the docstring, which now says only "passes on this tree" (:169 carries that). The :167 comment now records that state as something seen when the test was written, not something asserted. The boundary the phrase described is now asserted in a repo the test controls: `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk` commits dist and src at the same time, leaves src clean, makes dist an hour older on disk, and :242 asserts `outcome == "passed"`. The docstring's last bullet now includes "or at the same time as a clean src, though older on disk".</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (whole-claim, C1 one mutation hits one pair): added the 15-way parametrized per-fixture-input test at :172–186. Each run makes the current dist wrong on exactly one input (control at :180) and requires failure (:184) with the wrong value in the message (:185). A durable test checking only some pairs now goes red on each pair it leaves out. Observed with a `subset` probe variant.
Claim RECOMMENDATION 1 (D2), taken: :162–163 assert that the fixture holds exactly the PINNED pairs.
Claim RECOMMENDATION 2 (D4), taken: the docstring no longer asserts the real tree's state, and :167 records it as seen when the test was written. The boundary is pinned in a controlled repo instead (:242).
Claim RECOMMENDATION 3 (bounds), taken: new `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk`, with equal commit times, clean src and dist older on disk, expects passed (:242). Observed: the `mtime_only` and new `equal_is_stale` (>= commit rule) probe variants both go red there.
Shape RECOMMENDATION 1 (`"git" in message` at :270): left as is. The durable test's git-missing wording is not pinned by any requirement, so any exact string I chose would be invented.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>test_10_normalise_instance_hosts_phase2.py:160 — node running the real dist returns exactly PINNED for all 15 inputs. :163 — the fixture's pairs are exactly PINNED. :169 — the durable crawler test reports passed on this tree. :184/:185 — for each of the 15 fixture inputs in turn, with a current dist wrong on that input alone (control :180), the durable test reports failure and the message contains `wrong-host.invalid`. :197/:198 — with the realistic `.toLowerCase()` removal, it fails naming 'Tube.Example'.</assertion>
<expected>:160 and :163 equality holds. :169 "passed". :184 "failure" and :185 true for every one of the 15 parametrized inputs. :197 "failure" with 'Tube.Example' in the message.</expected>
<wrong_implementation>A durable crawler test that compares only some fixture pairs (observed with the `subset` variant, which drops the last pair): :184 reads "passed" for `'https://tube.example./'`. One that never compares dist's output (`no_compare`): :184 reads "passed" for all 15. One that skips or does not exist: :169 reads "skipped"/"not collected". A fixture that has drifted from the requirements: :163 goes red.</wrong_implementation>
</row>
<row clause="C2">
<assertion>test_10_normalise_instance_hosts_phase2.py:205/:206 (no node), :211/:212 (missing dist), :222/:223 (src committed after dist, dist newer on disk), :253/:254 (uncommitted src edit, equal commit times), :262/:263 (dist has no history and is older): each asserts outcome == "failure" and the build hint in the junit message. :269 fails without git. Contrasts: :232 and :242 assert "passed" when dist was committed after src, or at the same time as a clean src, though older on disk. :186 and :199 assert that a current-but-wrong dist is not reported as stale.</assertion>
<expected>"failure" with BUILD_HINT in the message in each stale, missing or no-node scenario. "passed" at :232 and :242. No BUILD_HINT at :186 and :199.</expected>
<wrong_implementation>pytest.skip on a missing node: :205 reads "skipped". Mtime-only staleness: :222 reads "passed", and :232 and :242 read "failure". Commit-time-only staleness: :253 and :262 read "passed". A >= commit-time rule: :242 reads "failure". A test that always fails with the hint: :169 and :232 read "failure".</wrong_implementation>
</row>
</rows>

<answers>
1. No. Each BUILD_HINT-absent check (:186, :199) is paired with outcome == "failure" and the wrong value present in the message. If the durable test is deleted, every run reads "not collected" and goes red.
2. No. PINNED is hand-written from the requirements. The per-input expectation at :180 is PINNED with one key replaced by a sentinel the test itself injects, not a recomputation of normalizeHostToken. Removing `.toLowerCase()` from dist's normalizeHostToken, or dropping any pair from the durable test's comparison, turns a run red.
3. No. That was the CRITICAL, and it is fixed: the wrong-value observable is now read at all 15 fixture inputs (:172) as well as the realistic mutation (:189). The freshness outcome is read at seven controlled states plus this tree.
4. No. No double. The only rewrite is a real copy of the crawler's own dist with one export wrapped, run under real node. The SRC/DIST redirect plugin only repoints paths.
5. Yes, it collects. `import pytest` was added. FIXTURE_PAIRS, EXPORT_LINE, WRONG_HOST and `_dist_outputs` are all bound. The harness collected 27 checkpoint tests (10 + 15 parametrized + 1 new, plus the premise test) across 8 variants, 208 in total, and all ran.
6. Yes. ValidateTests ["tests/tmp/probe_phase2_harness.py", "-q", "-rfE"] ran the edited checkpoint against the probe durable copy: 180 passed, 28 failed. The correct variant passed everything, which confirms the :180 control holds under node and that `wrong-host.invalid` appears in the junit message. `subset` failed only at the dropped pair, and `equal_is_stale` failed at :169 and :242.
7. Predicted, not observed. I did not run the gating checkpoint against today's phase-1 durable file, because that run belongs to the workflow. There, `-k crawler_dist` selects nothing, so every durable-run assertion reads "not collected" and goes red, while the premise test (:160, :163) passes, since the fixture and PINNED match on disk. Probe files I cannot delete and that need the operator to remove them (none matches test_*.py): tests/tmp/probe_phase2_env.py, tests/tmp/probe_durable_host.py, tests/tmp/probe_phase2_harness.py.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - red (audit round 2)

`tests/tmp/test_10_normalise_instance_hosts_phase2.py` exited 1.

```
  tests/tmp/test_10_normalise_instance_hosts_phase2.py  25 failed, 1 passed                    0.0s
  ----------------------------------------------------
  total                                                 25 failed, 1 passed                    5.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this (rules/shape.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:160
   assert _dist_outputs(REAL_DIST) == PINNED
   test_crawler_dist_under_node_returns_pinned_values checks the real dist and the fixture,
   and the phase writes neither. Its comment says it is already true before the phase (line 158),
   so it will pass against a stub durable test. The file still blocks a stub because every other
   test runs the durable test. shape.md has no entry for a premise test inside a checkpoint.
   It is noted here so that nobody reads this test's green result as evidence the phase is done.

PREDICTED FAILURE
The durable file tests/active/test_host_normalisation.py has no test matching `-k crawler_dist`
yet, so `_run_crawler_test` returns "not collected" every time.
- Line 169 fails on `assert outcome == "passed", message`.
- Lines 184, 197, 205, 211, 222, 232, 242, 253, 262 and 269 fail the same way on their
  `assert outcome == ...` line, and so does each of the 15 parametrized cases at line 184.
- test_crawler_dist_under_node_returns_pinned_values (lines 157-163) passes.

NOT ASSESSED
1. `fixtures_path` was not supplied. The checkpoint uses only pytest's built-in `tmp_path`.
   I did not read the `conftest.py` that the durable file imports `ROOT` from (line 11). Nothing
   in the checkpoint depends on it.
2. I read `code_under_test` in its current form. The durable `crawler_dist` test the checkpoint
   drives does not exist yet, so the stub question was answered from how the checkpoint's
   assertions are built. That covers the outcome and message checks paired with the "must pass"
   controls at lines 169, 232 and 242, and the 15-input parametrization at line 172.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (29 clauses: 7 must_prove, 12 docstring, 10 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "`dist/host-filters.js` run under node returns" the expected value for every pinned input | :160 | a dist that gets any one of the 15 inputs wrong or leaves one out. The whole dict is compared, so if `zip` truncates, a key goes missing and equality fails | CARRIED |
| C1b | must_prove | the crawler test holds dist to "each fixture pair" | :184, :185 (control :180) | a crawler test that checks only some of the pairs. The test is parametrised over every fixture input (:172), and each run's dist is wrong on that one input only (:180), so leaving out any pair lets one run pass | CARRIED |
| C2a | must_prove | "a missing node" makes the crawler test fail rather than skip | :205, :206 | a skip, an error, no test collected, or a failure without the build hint when node is off PATH | CARRIED |
| C2b | must_prove | "a missing dist" fails rather than skips | :211, :212 | a skip, error or silent pass when DIST does not exist | CARRIED |
| C2c1 | must_prove | "a stale dist" (src committed after dist) fails | :222, :223 | a check that only compares mtimes, because dist is newer on disk here (:220), and a skip | CARRIED |
| C2c2 | must_prove | "a stale dist" (uncommitted src edit newer on disk) fails | :253, :254 | a check that only compares commit times, because the commit times are equal (:247–248) | CARRIED |
| C2c3 | must_prove | "a stale dist" (dist has no history and is older on disk) fails | :262, :263 | a check that skips or passes when git has no commit time for dist | CARRIED |
| D1 | docstring | "imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values" | :160 | a dist that differs on any pinned input | CARRIED |
| D2 | docstring | "so with phase 1 the Python port equals the crawler on the fixture" | :162, :163 (with :160) | a fixture that differs from PINNED, or holds a duplicated input, so it no longer matches the dist's output. The fixture is now pinned to the same pairs the dist is held to | CARRIED |
| D3 | docstring | "passes on this tree" | :169 | a skipping, erroring or missing crawler test ("not collected" ≠ "passed") | CARRIED |
| D4 | docstring | withdrawn | n/a | n/a | CARRIED |
| D5 | docstring | "fails, without the build hint, on a current dist that returns a wrong value for one input" | :184–186, :197–199 | a crawler test that does not compare dist's output, or that reports it as staleness (:186, :199) | CARRIED |
| D6 | docstring | fails, never skips, with the build hint "when node is off PATH" | :205, :206 | a skip, or a failure without the hint | CARRIED |
| D7 | docstring | "... when dist is missing" | :211, :212 | the same, for a missing dist | CARRIED |
| D8 | docstring | "... when src was committed after dist" | :222, :223 | a check that only compares mtimes | CARRIED |
| D9 | docstring | "... when src has an uncommitted edit newer on disk than dist" | :253, :254 | a check that only compares commit times | CARRIED |
| D10 | docstring | "... when dist has no history and is older on disk than src" | :262, :263 | a skip or pass when dist has no commit history | CARRIED |
| D11 | docstring | "it fails when git is off PATH" | :269, :270 | a skip or pass without git | CARRIED |
| D12 | docstring | "passes when dist was committed after src ... though older on disk" | :232 | a crawler test that always fails, or one that only compares mtimes | CARRIED |
| N1 | name | `test_crawler_dist_under_node_returns_pinned_values` | :160 | a dist with any wrong pinned value | CARRIED |
| N2 | name | `test_durable_crawler_test_passes_on_this_tree` | :169 | a skipping or missing crawler test | CARRIED |
| N3 | name | `..._fails_on_current_dist_with_one_wrong_value` | :197, :198 | a crawler test that does not compare values | CARRIED |
| N4 | name | `..._fails_loudly_without_node` | :205, :206 | a skip, or a failure with no hint | CARRIED |
| N5 | name | `..._fails_loudly_when_dist_is_missing` | :211, :212 | the same | CARRIED |
| N6 | name | `..._fails_loudly_when_src_committed_after_dist` | :222, :223 | a check that only compares mtimes | CARRIED |
| N7 | name | `..._passes_when_dist_committed_after_src_though_older_on_disk` | :232 | a check that always fails or only compares mtimes | CARRIED |
| N8 | name | `..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist` | :253, :254 | a check that only compares commit times | CARRIED |
| N9 | name | `..._fails_loudly_when_dist_has_no_history_and_is_older` | :262, :263 | a skip or pass with no history | CARRIED |
| N10 | name | `..._fails_without_git` | :269 | a skip or pass without git | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:4
   D4 is withdrawn. The docstring sentence "whose dist is committed with src but is older on disk" was removed. The test does not assert anything about the real tree's state. That premise now appears only as a comment at :167. Its behaviour was moved into a controlled repo instead: `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk` (:235–242) carries the new docstring clause "or at the same time as a clean src, though older on disk" at :242. The prose was narrowed and a relocated assertion was added. No assertion was added about the real tree.
2. whole-claim (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase2.py:173, :235
   Two tests that the ledger does not name are new this round: `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input` and `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk`. Both of their name clauses are carried: the first at :184–186 with control :180, the second at :242. I found no claim defect in either.

NOT ASSESSED
1. `code_under_test` tests/active/test_host_normalisation.py, as read, has no `crawler_dist` test and no `SRC`/`DIST` Path constants. So I could not confirm from the code what the `PATHS_PLUGIN` redirection (:56–67) targets, or what the durable test's messages will contain. The C1b, C2 and D5–D12 rows were judged from the test's assertions and its junit-outcome harness (:77–102) alone.
2. engine/crawler/src/host-filters.ts and engine/crawler/dist/host-filters.js were not supplied and did not resolve by Glob. So I could not check the premise at :176 and :192 that `EXPORT_LINE` and `LOWERCASE_LINE` each appear exactly once. The test asserts both itself.

## 2026-09-26 - Step 7 - Phase 2 (Crawler parity and loud failure) - checkpoint outcome (run 1)

`tests/tmp/test_10_normalise_instance_hosts_phase2.py` exited 0 after the phase landed.

<changes>
### `tests/active/test_host_normalisation.py`
- I added one test, `test_crawler_dist_returns_pinned_values`. It is not parametrized, so `-k crawler_dist` selects exactly that one test. It runs through these checks in order:
  1. `node` must be on PATH. If not, it fails with the build hint `cd engine/crawler && npm install && npm run build`.
  2. `DIST` must exist. If not, it fails with the build hint.
  3. `git` must be on PATH. If not, it fails and names git.
  4. `DIST` must not be older than `SRC`. If it is, it fails with the build hint.
  5. It loads `DIST` in node through its file:// URL, runs `normalizeHostToken` on every input in `host_tokens.json`, and fails if any value differs. The message lists each wrong input with `repr(actual)` and `repr(expected)`, and has no build hint.
- `_dist_is_stale` decides step 4:
  - When both files are committed and clean, it compares git commit times (`git log -1 --format=%ct`) with a strict `>`. A checkout sets file mtimes arbitrarily, so on a clean tree they mean nothing.
  - When either file shows in `git status --porcelain` (an edit, or never committed) or has no commit, it compares mtimes instead.
  - git runs from `ROOT`, so `GIT_DIR`/`GIT_WORK_TREE` in the environment can point it at another repo.
- The paths are the module-level `Path` constants `SRC` and `DIST`, read when the test runs, not at import. `BUILD_HINT` and `NODE_SCRIPT` are also module level.
- The module docstring has a new bullet for the crawler test. Added imports: `os`, `shutil`, `subprocess`.
- Nothing calls `pytest.skip`, so a missing prerequisite always fails the test.

### Probe (checked, then emptied)
I ran a throwaway probe, `tests/tmp/probe_git_outside_worktree.py`, and saw:
- With `GIT_DIR`/`GIT_WORK_TREE` set and git run from outside that work tree, absolute pathspecs work. `status` shows `??` for an untracked file and ` M` for an edited one, and `log` gives no output for a file never committed.
- In the real tree, src and dist are clean and both have commit time 1790369883.
- The new durable test passes on this tree when run in its own pytest with junit output.
- A long custom assert message comes through complete in junit's `message` attribute.
- Python is 3.14, so `zip(strict=True)` is available.

I haven't run the checkpoint itself, so none of its other scenarios have been seen passing yet: wrong values, missing node/git/dist, and the stale and not-stale git cases. The workflow's run of the checkpoint will be the first check of those. I had no delete tool, so the probe file is emptied to a docstring and still needs deleting.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_git_outside_worktree.py — the probe I used to check git behaviour and the junit message before writing the test. It now holds only a docstring (no tests) because I had no delete tool; please delete it.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_10_normalise_instance_hosts_phase2.py  26 passed                              0.0s
  ----------------------------------------------------
  total                                                 26 passed                              5.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`fetch_hosts` in sync-whitelist.py and `fetch_join_hosts` in updater-worker.py pass every hosts-list entry through `normalize_host_token` in place of `strip().lower()`.

- C1 - `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`, which `sync_hosts` stores as one row.
- C2 - Entries that normalise to None are dropped, and `fetch_join_hosts` returns the same host set as `fetch_hosts`.

must_prove:
- C1 - `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`, which `sync_hosts` stores as one row.
- C2 - Entries that normalise to None are dropped, and `fetch_join_hosts` returns the same host set as `fetch_hosts`.

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - self-check (audit round 1, send-back 0)

`tests/tmp/test_10_normalise_instance_hosts_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:44 — `sync_whitelist.fetch_hosts(url)` on the list payload `["https://Tube.Example/", "tube.example"]`, served as a tmp_path file:// URI, `== {"tube.example"}` - expected: {"tube.example"}. The probe ran `normalize_host_token` on both entries and got 'tube.example' for each, so a job that routes entries through it yields this one-element set. - excludes: The current `str(host).strip().lower()` at sync-whitelist.py:243. The checkpoint run showed it returns {'https://tube.example/', 'tube.example'} ("Extra items in the left set: 'https://tube.example/'"). Calling `normalize_host` instead of `normalize_host_token`, or lowercasing without stripping the scheme, also keeps the two spellings apart.
- C1 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:48 — `sync_whitelist.sync_hosts(conn, hosts) == (1, 0, 1)` on a fresh `ensure_whitelist_schema` in a tmp_path SQLite file, with `hosts` taken from the fetch at line 43 - expected: (1, 0, 1). The probe got SYNC_ONE (1, 0, 1) for {"tube.example"} on a fresh schema. - excludes: With the un-normalised fetch, `hosts` holds both spellings. The probe got SYNC_TWO (2, 0, 2) for {"tube.example", "https://tube.example/"}, which this assertion rejects even if line 44 were loosened.
- C1 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:49 — `SELECT host FROM instances` on the same connection returns exactly `[("tube.example",)]` - expected: [('tube.example',)]. The probe got ROWS_ONE [('tube.example',)] after syncing {"tube.example"}. - excludes: Storing both spellings, as the un-normalised fetch does. The probe got ROWS_TWO [('https://tube.example/',), ('tube.example',)].
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:58 — `sync_whitelist.fetch_hosts(url)` on the `{"data": [{"host": e}, ...]}` payload of "", "   ", ".", "https://", "tube.example.", "https://Other.Example/videos" `== {"tube.example", "other.example"}` - expected: {"tube.example", "other.example"}. The probe got None for "", "   ", "." and "https://", 'tube.example' for "tube.example." and 'other.example' for "https://Other.Example/videos" from `normalize_host_token`. - excludes: The current strip/lower. Both the checkpoint run and the probe (SYNC_NOW) returned {'.', 'https://other.example/videos', 'tube.example.', 'https://'}, so "." and "https://" are kept instead of dropped. An implementation that normalises but then adds a None or empty value to the set would also differ. The two kept hosts serve as the positive control: an implementation that drops everything fails too.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:59 — `updater_worker.fetch_join_hosts(url)` on the same payload `== {"tube.example", "other.example"}`, the same literal as line 58, so the two fetchers must agree with each other - expected: {"tube.example", "other.example"}, by the same observed `normalize_host_token` values as line 58. - excludes: Changing only sync-whitelist.py and leaving updater-worker.py:438 as `str(host).strip().lower()`. The probe (JOIN_NOW) showed that returns {'.', 'https://other.example/videos', 'tube.example.', 'https://'}, so line 58 would pass and this line would fail.
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:65 — `fetch_hosts` on the list payload "", "   ", ".", "https://" raises ValueError whose message is exactly "Whitelist contained no hosts." - expected: ValueError("Whitelist contained no hosts."). The probe showed all four entries normalise to None, which leaves the set empty and reaches the existing raise at sync-whitelist.py:248. - excludes: The current strip/lower. The checkpoint run showed "Failed: DID NOT RAISE ValueError", because "." and "https://" survive into the set. An implementation that adds the None results to the set would also avoid the raise.

<assertions>
tests/tmp/test_10_normalise_instance_hosts_phase3.py:44 — `fetch_hosts` on the list payload ["https://Tube.Example/", "tube.example"], served as a file:// URI from tmp_path, returns exactly {"tube.example"}. Before the phase it returns {"https://tube.example/", "tube.example"}. — C1
tests/tmp/test_10_normalise_instance_hosts_phase3.py:48 — after `ensure_whitelist_schema` on a fresh SQLite file in tmp_path (never the shared whitelist.db), `sync_hosts(conn, <fetch_hosts output>)` returns (1, 0, 1). The old output would give (2, 0, 2). — C1
tests/tmp/test_10_normalise_instance_hosts_phase3.py:49 — the `instances` table then holds exactly one row, [("tube.example",)]. — C1
tests/tmp/test_10_normalise_instance_hosts_phase3.py:58 — `fetch_hosts` on the dict payload {"data": [{"host": e} ...]} with entries "", "   ", ".", "https://", "tube.example.", "https://Other.Example/videos" returns exactly {"tube.example", "other.example"}. Before the phase it returns {".", "https://", "tube.example.", "https://other.example/videos"}. — C2
tests/tmp/test_10_normalise_instance_hosts_phase3.py:59 — `fetch_join_hosts` in updater-worker.py, on the same payload, returns the same exact set {"tube.example", "other.example"}. Before the phase it returns {".", "https://", "https://other.example/videos", "tube.example."}. — C2
tests/tmp/test_10_normalise_instance_hosts_phase3.py:65 — regression guard, not a new clause: `fetch_hosts` on ["", "   ", ".", "https://"], where every entry normalises to None, raises ValueError whose message matches ^Whitelist contained no hosts\.$ in full. Before the phase it does not raise and returns {".", "https://"}. — C2
</assertions>

<probes>
Ran ValidateTests ["tests/tmp/test_10_normalise_instance_hosts_phase3.py", "-v"] on the pre-phase tree. Both job files loaded through importlib.util.spec_from_file_location in the module-scoped fixture. The file:// fetch worked through urlopen. All 3 tests failed on their assertions, not in setup. fetch_hosts(list payload) returned {'https://tube.example/', 'tube.example'}. fetch_hosts(dict payload) returned extras '.', 'https://', 'https://other.example/videos', 'tube.example.'. The all-None payload printed "DID NOT RAISE ValueError".
Ran ValidateTests ["tests/tmp/probe_phase3.py", "-s"], a probe that imports this file's helpers, to reach the values the first run stopped short of. It printed: SYNC_ONE (1, 0, 1) [('tube.example',)], so ensure_whitelist_schema plus sync_hosts({"tube.example"}) on a fresh tmp_path DB gives exactly the expected tuple and row. SYNC_OLD (2, 0, 2), so the old two-host set gives a different tuple. JOIN_DICT ['.', 'https://', 'https://other.example/videos', 'tube.example.'], which is the old fetch_join_hosts result on the dict payload. ALL_NONE_SYNC ['.', 'https://'], which is the old fetch_hosts result on the all-None payload.
Probe cleanup: I have no tool that deletes files, so tests/tmp/probe_phase3.py is still on disk and needs removing. It is outside the one file I was given. pytest's default python_files pattern (test_*.py) will not collect it, and pyproject.toml does not override that pattern.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_10_normalise_instance_hosts_phase3.py` - 2901 characters, inlined in full

```
"""Phase 3 checkpoint: the whitelist-sync and updater jobs normalise hosts-list entries with `normalize_host_token`.

- `fetch_hosts` in sync-whitelist.py reads a list payload `["https://Tube.Example/", "tube.example"]` as the one host `tube.example`, and `sync_hosts`, given that set on a fresh whitelist schema in a tmp_path SQLite file, returns (1, 0, 1) and leaves exactly the row `tube.example`.
- On a `{"data": [...]}` payload whose `""`, `"   "`, `"."` and `"https://"` entries normalise to None, `fetch_hosts` and `fetch_join_hosts` in updater-worker.py both drop those entries and return exactly `{"tube.example", "other.example"}`.
- `fetch_hosts` on a payload whose every entry normalises to None still raises ValueError "Whitelist contained no hosts.".
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"

DROPPED = ["", "   ", ".", "https://"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jobs():
    return _load("sync_whitelist_job", JOBS_DIR / "sync-whitelist.py"), _load("updater_worker_job", JOBS_DIR / "updater-worker.py")


def _serve(tmp_path: Path, payload) -> str:
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.as_uri()


def test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row(jobs, tmp_path):
    sync_whitelist, _ = jobs
    url = _serve(tmp_path, ["https://Tube.Example/", "tube.example"])
    hosts = sync_whitelist.fetch_hosts(url)
    assert hosts == {"tube.example"}  # C1
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        sync_whitelist.ensure_whitelist_schema(conn)
        assert sync_whitelist.sync_hosts(conn, hosts) == (1, 0, 1)  # C1
        assert conn.execute("SELECT host FROM instances").fetchall() == [("tube.example",)]  # C1
    finally:
        conn.close()


def test_both_fetchers_drop_entries_that_normalise_to_none(jobs, tmp_path):
    sync_whitelist, updater_worker = jobs
    entries = [*DROPPED, "tube.example.", "https://Other.Example/videos"]
    url = _serve(tmp_path, {"data": [{"host": entry} for entry in entries]})
    assert sync_whitelist.fetch_hosts(url) == {"tube.example", "other.example"}  # C2
    assert updater_worker.fetch_join_hosts(url) == {"tube.example", "other.example"}  # C2


def test_fetch_hosts_still_raises_when_every_entry_normalises_to_none(jobs, tmp_path):
    sync_whitelist, _ = jobs
    url = _serve(tmp_path, DROPPED)
    with pytest.raises(ValueError, match="^Whitelist contained no hosts\\.$"):  # C2
        sync_whitelist.fetch_hosts(url)

```


Gate: satisfied

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - red (audit round 1)

`tests/tmp/test_10_normalise_instance_hosts_phase3.py` exited 1.

```
  tests/tmp/test_10_normalise_instance_hosts_phase3.py  3 failed                               0.0s
  ----------------------------------------------------
  total                                                 3 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D1

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row fails at line 44 on
`assert hosts == {"tube.example"}` because fetch_hosts returns
{"https://tube.example/", "tube.example"}. test_both_fetchers_drop_entries_that_normalise_to_none
fails at line 58 because fetch_hosts returns {".", "https://", "tube.example.",
"https://other.example/videos"}. test_fetch_hosts_still_raises_when_every_entry_normalises_to_none
fails at lines 65-66 with "DID NOT RAISE ValueError", because "." and "https://" survive
the current strip/lower and leave the host set non-empty.

NOT ASSESSED
1. `fixtures_path` was not supplied. The test defines its only non-builtin fixture
   (`jobs`, line 29-31) and otherwise uses pytest's `tmp_path`. No conftest was needed
   to answer the shape questions, and none was read.
2. The test imports both job modules with `spec_from_file_location` (lines 22-31).
   Those imports pull in `scripts.cli_format`, `server_config` and `data.moderation`,
   which were not read. Whether that import succeeds was not checked, so the predicted
   failure assumes collection gets past the `jobs` fixture.
```

### devsecops-test-claim-auditor

```
CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (16 clauses: 4 must_prove, 8 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example` | :44 | strip-and-lowercase only, which gives {"https://tube.example/", "tube.example"}. A scheme or trailing slash left in place breaks set equality | CARRIED |
| C1b | must_prove | "which `sync_hosts` stores as one row" | :48, :49 | two rows stored, or a host stored with its scheme. (1,0,1) excludes total=2 or added=2, and the exact row list excludes any row other than `tube.example` | CARRIED |
| C2a | must_prove | "Entries that normalise to None are dropped" | :58, :59 | keeping `.` or `https://`, which strip/lower lets through. Keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these | CARRIED |
| C2b | must_prove | "`fetch_join_hosts` returns the same host set as `fetch_hosts`" | :58, :59 | updater-worker left on its own normaliser. Both fetchers read the same payload and are held to the same literal set, so any difference on this input fails | CARRIED |
| D1 | docstring | "normalise hosts-list entries with `normalize_host_token`" | none | nothing. A hand-rolled normaliser that matches on these six inputs passes. No assertion ties either fetcher's output to `normalize_host_token` | UNCARRIED |
| D2 | docstring | `fetch_hosts` reads `["https://Tube.Example/", "tube.example"]` as the one host `tube.example` | :44 | a set holding two hosts, or holding a URL form | CARRIED |
| D3 | docstring | `sync_hosts` on a fresh schema in a tmp_path SQLite file "returns (1, 0, 1)" | :48 | a wrong total, removed or added count | CARRIED |
| D4 | docstring | "leaves exactly the row `tube.example`" | :49 | any extra row, or a missing row | CARRIED |
| D5 | docstring | on a `{"data": [...]}` payload, `fetch_hosts` drops `""`, `"   "`, `"."`, `"https://"` | :58 | any of the four kept as a host | CARRIED |
| D6 | docstring | `fetch_join_hosts` in updater-worker.py drops the same entries | :59 | any of the four kept as a host | CARRIED |
| D7 | docstring | both "return exactly `{"tube.example", "other.example"}`" | :58, :59 | a trailing dot, path, scheme or case left in place | CARRIED |
| D8 | docstring | `fetch_hosts` on an all-None payload "still raises ValueError 'Whitelist contained no hosts.'" | :65 | returning an empty set or a set containing `.`/`https://`, or raising with a different message (anchored regex) | CARRIED |
| N1 | name | test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: "collapses url and bare host" | :44 | two hosts kept | CARRIED |
| N2 | name | same test: "into one synced row" | :48, :49 | more than one row, or a different row | CARRIED |
| N3 | name | test_both_fetchers_drop_entries_that_normalise_to_none | :58, :59 | either fetcher keeping a None-normalising entry | CARRIED |
| N4 | name | test_fetch_hosts_still_raises_when_every_entry_normalises_to_none | :65 | no raise on an all-None payload | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase3.py:1
   D1 is UNCARRIED. The docstring says both jobs normalise "with `normalize_host_token`",
   but every assertion compares against a literal set built from six hand-picked inputs.
   Nothing excludes a local normaliser that agrees on those six and diverges elsewhere.
   One fix is to add an assertion that runs every `input` from `tests/active/host_tokens.json`
   through both fetchers and compares the result with the non-None `normalize_host_token`
   outputs. The other is to narrow the docstring sentence. D1 is not in `must_prove`, so this
   does not block.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase3.py:62
   The failure mode is tested only for `fetch_hosts`. `fetch_join_hosts` has no test for a
   payload where every entry normalises to None, so its expected behaviour there (unlike
   `fetch_hosts` it has no empty-set raise) is not established.
3. bounds (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase3.py:19
   `DROPPED` covers empty, whitespace-only, a lone dot and a bare scheme. Nothing covers
   non-string edges the fetchers accept: a `{"data": [...]}` entry whose `host` is null or
   missing, or a non-string list entry. C2b ("same host set") is also checked on the dict
   payload only. The list-shaped payload from :42 never goes through `fetch_join_hosts`.

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and its
   own module-scoped `jobs` fixture (:29–31), so no conftest was needed for independence.
   The `conftest.py` that `tests/active/test_host_normalisation.py` imports `ROOT` from was
   not read.
2. `data.moderation.normalize_host_token`, which the docstring (D1) and `must_prove` C2
   ("normalise to None") refer to, was not in `code_under_test` and was not read. Whether
   the four `DROPPED` entries really do normalise to None was taken from the test's own
   premise and was not checked against that function.
```

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - self-check (audit round 2, send-back 0)

`tests/tmp/test_10_normalise_instance_hosts_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:44, :48, :49 — fetch_hosts(["https://Tube.Example/", "tube.example"]) == {"tube.example"}; then sync_hosts on a fresh tmp_path schema == (1, 0, 1); then the instances table holds exactly [("tube.example",)] - expected: {"tube.example"}, then (1, 0, 1), then [("tube.example",)] - excludes: Strip-and-lowercase only, which is the pre-phase code. On a run it returned {"https://tube.example/", "tube.example"}, and syncing that set gives (2, 0, 2) and two rows (the probe observed SYNC_OLD (2, 0, 2)).
- C2 - tests/tmp/test_10_normalise_instance_hosts_phase3.py:58, :59 — fetch_hosts and fetch_join_hosts, fed the same {"data": [...]} payload ("", "   ", ".", "https://", "tube.example.", "https://Other.Example/videos"), each return exactly {"tube.example", "other.example"} - expected: {"tube.example", "other.example"} from both fetchers - excludes: Pre-phase strip/lower in either job. On a run it returned {".", "https://", "tube.example.", "https://other.example/videos"}. Also excluded: updater-worker left on its own normaliser while sync-whitelist is fixed, which fails :59 on its own.

<items>
<item id="D1">
<disposition>justified</disposition>
<what>I narrowed the docstring's summary sentence on line 1 so it matches what the test asserts. It no longer says the jobs normalise "with `normalize_host_token`". It now says they "normalise hosts-list entries to bare lowercase hosts, as pinned by the literal inputs below". No assertion claims to tie either fetcher to that function. The claim that matters, that both fetchers agree on the same host set (C2b), is still carried at :58 and :59. I did not add an assertion that runs `normalize_host_token` inside the test. That would make the test perform production's own transformation and compare production with itself, which is the mirroring the shape audit warns about. Only the docstring line changed, so every assertion keeps its line number.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. I did not take any of the three claim-audit RECOMMENDATIONS. Rec 1 (D1) I handled by narrowing the docstring, not by adding an assertion that mirrors normalize_host_token. Rec 2 (fetch_join_hosts on an all-None payload) and rec 3 (null or non-string entries, and the list payload through fetch_join_hosts) would pin behaviour that no must_prove clause asks for. I left them as they are. They do not block.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:44, :48, :49 — fetch_hosts(["https://Tube.Example/", "tube.example"]) == {"tube.example"}; then sync_hosts on a fresh tmp_path schema == (1, 0, 1); then the instances table holds exactly [("tube.example",)]</assertion>
<expected>{"tube.example"}, then (1, 0, 1), then [("tube.example",)]</expected>
<wrong_implementation>Strip-and-lowercase only, which is the pre-phase code. On a run it returned {"https://tube.example/", "tube.example"}, and syncing that set gives (2, 0, 2) and two rows (the probe observed SYNC_OLD (2, 0, 2)).</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_10_normalise_instance_hosts_phase3.py:58, :59 — fetch_hosts and fetch_join_hosts, fed the same {"data": [...]} payload ("", "   ", ".", "https://", "tube.example.", "https://Other.Example/videos"), each return exactly {"tube.example", "other.example"}</assertion>
<expected>{"tube.example", "other.example"} from both fetchers</expected>
<wrong_implementation>Pre-phase strip/lower in either job. On a run it returned {".", "https://", "tube.example.", "https://other.example/videos"}. Also excluded: updater-worker left on its own normaliser while sync-whitelist is fixed, which fails :59 on its own.</wrong_implementation>
</row>
</rows>

<answers>
1. No. There is no absence-only assertion. Every check is an exact set, tuple or row list with positive members, and the raise at :65 is a positive pytest.raises check with an anchored message.
2. No. Every expected value is a literal, and the test does not normalise anything itself. That is why I narrowed the docstring and did not add a normalize_host_token comparison. Deleting the new normalisation call in fetch_hosts turns :44, :58 and :65 red. Deleting it in fetch_join_hosts turns :59 red.
3. No. Normalisation is checked on six distinct inputs across two payload shapes, and C2b holds two independent fetchers to one literal set, not to each other.
4. No. There are no doubles. The real modules are loaded, the fetchers read a real file:// URI, and sync_hosts writes to a real SQLite file.
5. Yes, it collects. Only the docstring changed. The imports, names and three test functions are unchanged from the version that collected and ran in the earlier probe.
6. Yes, the values were observed. The pre-phase outputs and SYNC_ONE (1, 0, 1) [('tube.example',)] come from the earlier ValidateTests runs quoted in my previous reply.
7. Yes, it is still red for its own reason. The docstring edit touches no executable line, so the earlier run still stands: all three tests fail on their assertions because the phase has not been built.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - red (audit round 2)

`tests/tmp/test_10_normalise_instance_hosts_phase3.py` exited 1.

```
  tests/tmp/test_10_normalise_instance_hosts_phase3.py  3 failed                               0.0s
  ----------------------------------------------------
  total                                                 3 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails first at line 44 on `assert hosts == {"tube.example"}`, because `fetch_hosts`
still only strips and lowercases each entry, so it returns
{"https://tube.example/", "tube.example"}. Line 58 fails the same way: the set still holds
".", "https://", "tube.example." and "https://other.example/videos". Line 65 fails with
"DID NOT RAISE", because "." and "https://" pass the `if host_value:` check at
sync-whitelist.py:244, so the set is not empty and no ValueError is raised.

NOT ASSESSED
1. `fixtures_path` was not supplied. The test defines its own fixtures and helpers
   (`jobs`, `_serve`, `_load`, lines 22–37) and uses no conftest fixture, so nothing was
   left unread.
2. `code_under_test` is labelled EDITED, but sync-whitelist.py:219–250 and
   updater-worker.py:414–441 contain no normalisation call. The prediction is made against
   those files as they read now.
3. tests/active/test_host_normalisation.py is listed in `code_under_test`. The test under
   audit does not import or exercise it, so no finding was drawn from it.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (16 clauses: 4 must_prove, 8 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example` | :44 | Strip-and-lowercase only, which gives {"https://tube.example/", "tube.example"}. A scheme or trailing slash left in place fails the exact set equality | CARRIED |
| C1b | must_prove | "which `sync_hosts` stores as one row" | :48, :49 | Two rows stored, or a host stored with its scheme. (1, 0, 1) excludes total=2 and added=2, and the exact row list excludes any row other than `tube.example` | CARRIED |
| C2a | must_prove | "Entries that normalise to None are dropped" | :58, :59 | Keeping `.` or `https://`, which strip/lower lets through, or keeping `tube.example.` unnormalised. Exact set equality from both fetchers excludes each of these | CARRIED |
| C2b | must_prove | "`fetch_join_hosts` returns the same host set as `fetch_hosts`" | :58, :59 | updater-worker left on its own normaliser. Both fetchers read one payload and are held to the same literal set, so any difference on this input fails | CARRIED |
| D1 | docstring | withdrawn | n/a | n/a | CARRIED |
| D2 | docstring | `fetch_hosts` reads `["https://Tube.Example/", "tube.example"]` as the one host `tube.example` | :44 | A set holding two hosts, or holding a URL form | CARRIED |
| D3 | docstring | `sync_hosts` on a fresh schema in a tmp_path SQLite file "returns (1, 0, 1)" | :48 | A wrong total, removed or added count | CARRIED |
| D4 | docstring | "leaves exactly the row `tube.example`" | :49 | Any extra row, or a missing row | CARRIED |
| D5 | docstring | on a `{"data": [...]}` payload, `fetch_hosts` drops `""`, `"   "`, `"."`, `"https://"` | :58 | Any of the four kept as a host | CARRIED |
| D6 | docstring | `fetch_join_hosts` in updater-worker.py drops the same entries | :59 | Any of the four kept as a host | CARRIED |
| D7 | docstring | both "return exactly `{"tube.example", "other.example"}`" | :58, :59 | A trailing dot, path, scheme or case left in place | CARRIED |
| D8 | docstring | `fetch_hosts` on an all-None payload "still raises ValueError 'Whitelist contained no hosts.'" | :65 | Returning an empty set or a set containing `.`/`https://`, or raising with a different message (the regex is anchored) | CARRIED |
| N1 | name | test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row: "collapses url and bare host" | :44 | Two hosts kept | CARRIED |
| N2 | name | same test: "into one synced row" | :48, :49 | More than one row, or a different row | CARRIED |
| N3 | name | test_both_fetchers_drop_entries_that_normalise_to_none | :58, :59 | Either fetcher keeping an entry that normalises to None | CARRIED |
| N4 | name | test_fetch_hosts_still_raises_when_every_entry_normalises_to_none | :65 | No raise on an all-None payload | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_10_normalise_instance_hosts_phase3.py:1
   D1 was UNCARRIED on the first audit. It clears this round because the prose was narrowed, not because an assertion was added. The docstring's opening sentence used to claim the jobs normalise "with `normalize_host_token`". It now reads "normalise hosts-list entries to bare lowercase hosts, as pinned by the literal inputs below", and the six literal inputs carry that narrower sentence. Nothing in the test ties either fetcher's output to `normalize_host_token`, or to the pinned pairs in `tests/active/host_tokens.json`. A hand-rolled normaliser that agrees on these six inputs still passes. The build should know this reuse is no longer claimed or checked here.

NOT ASSESSED
1. `fixtures_path` was not supplied. The test defines its own fixture (`jobs`, :29-31) and uses only pytest's built-in `tmp_path`, so it needs no conftest. `tests/active/test_host_normalisation.py` imports `ROOT` from a `conftest` that was not read, because that file is listed as code under test and is not the test under audit.

## 2026-09-26 - Step 7 - Phase 3 (Both jobs normalise through the helper) - checkpoint outcome (run 1)

`tests/tmp/test_10_normalise_instance_hosts_phase3.py` exited 0 after the phase landed.

<changes>
### `engine/server/db/jobs/sync-whitelist.py`
- The `data.moderation` import now also brings in `normalize_host_token`.
- In `fetch_hosts`, each entry is now normalised with `host_value = normalize_host_token(str(host))` instead of `str(host).strip().lower()`. The existing `if host_value:` guard already drops `None`, so entries that normalise to nothing are skipped. When no host is left, the function still raises `ValueError("Whitelist contained no hosts.")`. The User-Agent, error handling and payload-shape handling are unchanged.

### `engine/server/db/jobs/updater-worker.py`
- `normalize_host_token,` is added to the parenthesised `data.moderation` import, between `list_active_denied_hosts` and `purge_host_data`.
- `fetch_join_hosts` makes the same swap: `value = normalize_host_token(str(host))`. The existing `if value:` guard drops `None`. `list_prod_hosts` is untouched, as the plan says.

### `tests/active/test_host_normalisation.py`
- The module docstring has two new bullets covering the job behaviour.
- New imports: `importlib.util` and `sqlite3`. New constant: `JOBS_DIR = SERVER_DIR / "db" / "jobs"`.
- New helpers:
  - `_load_job` loads a job file with `spec_from_file_location`.
  - a module-scoped `jobs` fixture loads both jobs.
  - `_payload_url` writes the payload to `tmp_path` and returns a `file://` URI.
- Three new durable tests, one for each behaviour this phase delivers:
  - `test_sync_job_stores_one_spelling_per_host`: a list payload with `https://Tube.Example/` and `tube.example` gives `{"tube.example"}`. `sync_hosts` on a temp SQLite database returns `(1, 0, 1)` and stores the single row `tube.example`.
  - `test_jobs_drop_entries_that_normalise_to_none`: a `{"data": [...]}` payload with `""`, `"   "`, `"."` and `"https://"` plus two valid entries gives `{"tube.example", "other.example"}` from both `fetch_hosts` and `fetch_join_hosts`.
  - `test_sync_job_still_rejects_a_list_with_no_usable_host`: `fetch_hosts` raises `ValueError` with exactly "Whitelist contained no hosts.".

### What I ran
- I ran `ValidateTests tests/active/test_host_normalisation.py -k job`: 3 passed, 16 deselected, exit 0.
- I did not run the gating checkpoint. It exercises the same functions on the same inputs.
- I did not run the post-phase commands the plan lists: test-moderation-integration.py, test-orchestrator-smoke.py and the full validate_tests.py compared with the green baseline. They are still owed, and the smoke test counts as not run if node, dist, the embedding stack or the network is missing.
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
  tests/tmp/test_10_normalise_instance_hosts_phase3.py  3 passed                               0.0s
  ----------------------------------------------------
  total                                                 3 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_10_normalise_instance_hosts_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_10_normalise_instance_hosts_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_10_normalise_instance_hosts_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_10_normalise_instance_hosts_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_10_normalise_instance_hosts_phase3.py`

## 2026-09-26 - Step 8 - refactor pass

<refactors>
none. The worktree matches the inlined code, and the only duplication left is older than this build and was not added by it (see left_out).
</refactors>

<left_out>
1. Shared entry loop. `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py` and `fetch_join_hosts` in `engine/server/db/jobs/updater-worker.py` have the same payload-shape and entry-normalising loop. Moving it into one helper in `data.moderation` would guarantee C2 (both jobs return the same host set) by construction. I did not do it: the two copies existed before this build, the helper would be a new public function in `moderation.py`, and the two jobs still differ in User-Agent, fetch error text and the "no hosts" raise. The gating test already pins that they agree.
2. `if not host: continue` guard in both loops. It is not redundant and stays: `str(None)` is `"none"`, and `normalize_host_token` would keep that as a host.
3. Return annotation on `sync_hosts`. In sync-whitelist.py it says `tuple[int, int]` but the function returns three values. Fixing it would make the comment "despite its two-element annotation" in the gated `test_sync_job_stores_one_spelling_per_host` false, and I cannot edit that test. It is also older than this build.
4. Probe files. `tests/tmp/` still holds files from earlier turns that I have no tool to delete: probe_host_token.py, probe_git_outside_worktree.py, probe_durable_host.py, probe_phase2_env.py, probe_phase2_harness.py, probe_phase3.py, probe_phase3_seams.py and the test_10_normalise_instance_hosts_phase{1,2,3}.py checkpoint copies. The operator should remove the probes.
5. Pass criteria. The step's "What the pass is measured against" section arrived as the unfilled placeholder `{rat_tail_rules}`, so I checked the pass against the role's rules instead. The one `rat-tail:` comment, in `_whatwg_hostname`, names both its limit and its upgrade path.
6. Checks still owed from phase 3. test-moderation-integration.py, test-orchestrator-smoke.py and the full validate_tests.py baseline comparison have not been run.
</left_out>

<needs_fresh_red>
`engine/server/db/jobs/compare-join-hosts.py:80` also reads the JoinPeerTube hosts list, and it still uses `str(host).strip().lower()`. So it can disagree with the two jobs this build changed, for example by counting `https://Tube.Example/` as its own host. Switching it to `normalize_host_token` changes its output, so it is new behaviour, not a refactor. It needs its own phase and red, and it is outside the files this build approved.
</needs_fresh_red>

<observation>
The worktree matches the inlined code, and `normalize_host_token` has exactly two callers, `fetch_hosts` and `fetch_join_hosts`. No refactor was needed without changing either behaviour or code older than this build.
</observation>

## 2026-09-26 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 1 of 13 test groups (12 unchanged):
  test_host_normalisation.py — no map entry
  test_host_normalisation.py  19 passed                              0.0s
  --------------------------
  total                       19 passed                              0.2s wall, 1 lane

moved against the previous record:
       appeared  tests.active.test_host_normalisation::test_crawler_dist_returns_pinned_values
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['   ']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value[' Tube.Example ']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['.']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['..tube.example..']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['http://tube.example:8080/path']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['https://']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['https://Tube.Example/']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['https://[::1]:8080/']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['https://b\xfccher.example/']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['https://tube.example./']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['https://user@tube.example']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['tube.example.']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['tube.example/videos']
       appeared  tests.active.test_host_normalisation::test_python_port_returns_pinned_value['tube.example:9000']

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-26 - Step 9 - document triage

- [ ] `DATA_BUILD.md` - Section "2) Filter to JoinPeerTube whitelist". Its "Notes:" list (lines 145-149) says where the whitelist comes from and what include and exclude mode do. It says nothing about how entries are turned into hosts, and that is the behaviour this build changed. Add one bullet saying that `sync-whitelist.py`'s `fetch_hosts` passes every entry through `data.moderation.normalize_host_token`, which is a port of the crawler's `normalizeHostToken`, so the job stores the same spelling the crawler does:
- URL-like entries (`http(s)://…`, or anything containing `/`) keep only the hostname. Scheme, userinfo, port and path are dropped. IPv6 keeps its brackets and IDNs become punycode.
- Bare entries only have leading and trailing dots trimmed, so a bare `host:port` keeps its port.
- Entries that normalise to nothing (`""`, `.`, `https://`) are skipped.
- The job still fails with "Whitelist contained no hosts." if no entry is left.

The bullet should describe the current state only, with no "now" wording.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - The "What Exactly Is Collected" bullet on line 59 ("Instances: from whitelist source (JoinPeerTube URL by default).") is incomplete. It should say that with `--sync-join-whitelist` the fetched hosts (`fetch_join_hosts`) go through the crawler-equivalent `data.moderation.normalize_host_token` before they are compared with prod hosts and the denylist to work out the new and stale sets. Entries that normalise to nothing are dropped. Stale hosts are purged from the prod and similarity DBs only with `--yes`, and `--dry-run` shows the plan first.

Also state, without "previously" wording, that `instances` rows stored under a spelling other than the crawler's (for example with a scheme or trailing dots) show up as stale. Operators should review with `--dry-run` before passing `--yes`.

The "Important Flags" list (lines 101-115) has `--whitelist-url` but leaves out `--sync-join-whitelist`, `--yes` and `--dry-run`, which this behaviour depends on. Add them.
- [ ] `docs/project/issues/06-normalise-instance-hosts.md` - Changes at harvest:
- Tick the acceptance criteria. The table-driven Python test, the Node check against `dist/host-filters.js` over the shared `tests/active/host_tokens.json` fixture, the one-spelling sync, None entries dropped, and `fetch_join_hosts` == `fetch_hosts` are all delivered by `tests/active/test_host_normalisation.py`.
- The criterion "Existing moderation-integration and orchestrator smoke tests pass" may only be ticked once those standalone runs have actually happened. The build left them owed, along with the full `validate_tests.py` baseline comparison.
- Set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.
- Record where the helper landed: `normalize_host_token` in `engine/server/data/moderation.py`, next to the unchanged `normalize_host`.
- Record the dist-staleness rule: git commit times, with an mtime fallback when src is dirty or a file has no history. A missing node, dist or git fails the test and never skips it.
- Record the accepted limitations:
  - Branch 4 keeps `@ ? #` and ports.
  - Parity is proven only for the fixture inputs and on the interpreter that runs the test. The `rat-tail` note covers forbidden host code points, and IDNA 2003 vs UTS #46.
  - `compare-join-hosts.py` still uses strip/lower.
  - The crawler's `--whitelist-file` read-back strips dots from URL-form hosts that end in a dot.
  - `normalize_host` (denylist) does not bracket IPv6 or convert to punycode.
  - Existing rows are not rewritten.
- [ ] `docs/project/plans/10-normalise-instance-hosts.md` - At harvest, mark the plan delivered and point to the build plan `docs/project/plans/16-10-normalise-instance-hosts.md`. Its "Requirement: existing scripts and suite still pass" paragraph is now wrong: it says the smoke test "serves `whitelist.json` through `fetch_hosts`". Correct it to `fetch_join_hosts`, which the smoke test reaches through `updater-worker.py --whitelist-url`. Also note:
- Only `sync-whitelist.py` parses `schema.sql` at import.
- The updater's hosts file is not always a fixed point when the crawler reads it back. Dotted URL-form hosts change.
- The fixture holds 15 pairs, not 14. `https://tube.example./` → `tube.example.` was added.
- Fail-loudly was chosen over build-first, with the git-based staleness rule.
- Harvest should move the plan to `plans/archive/`, as delivered plans are.
- [ ] `docs/project/roadmap.md` - Add follow-up lines, all outside this build. The M6 moderation section or the security remainder is the natural home.
- Move `compare-join-hosts.py` (`hosts_from_payload` and `load_local_hosts`) onto `normalize_host_token`. It is now the only Python reader of the JoinPeerTube list that still uses strip/lower, and it can report hosts as missing when the jobs treat them as present.
- Make the crawler's `--whitelist-file` mode (`loadHostsFromFile`, where branch 4 strips dots) agree with its URL mode (which keeps the WHATWG trailing dot), so that dotted entries stop churning through purge and recrawl.
- Optionally, align `normalize_host` (denylist input) on bracketed IPv6 and punycode, so denylist entries match the join-host spelling.

At harvest, issue 06 closes. The M1 line "Open security issues: `01` to `07`" and step 1 of "Implementation order" (`04`, `05`, `06`) must stop listing 06 as open, and "Delivered" gains a line for issue 06 that points at the archived plan.

Out of scope:
- [ ] `DEPLOYMENT.md` - It mentions `sync-whitelist.py` only in the run-order warning on line 43: run it after `crawl:videos` completes. It says nothing about how hosts-list entries are parsed or normalised, and that ordering is unchanged.
- [ ] `README.md` - Line 14 says only that filtering keeps instances that appear in the JoinPeerTube whitelist. That is still true, and the README makes no claim about entry spelling.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - It describes the smoke test's inputs (`test-instances.json` or prod rows) and flow, and makes no claim about host normalisation or which fetch function is used. Its plain lowercase hosts pass through `normalize_host_token` unchanged, so nothing it says has become false.
- [ ] `docs/project/security-audit/run-2/REPORT.md` - This is a point-in-time audit record, not living documentation. Its line saying the moderation layer normalises hosts through `normalize_host` before comparing or deleting is still true: purges and serving filters still use `normalize_host`. The finding SI4-M1 is closed through the issue file, not by editing the report.
- [ ] `docs/project/adr/0001-derived-interaction-event-ids.md` - It covers interaction event ids. It does not touch host normalisation or the whitelist jobs. The same holds for ADRs 0002 (trusted proxy client address), 0003 (metadata endpoint uuid entries), 0004 (CORS) and 0005 (raw event retention). None of them makes a claim about JoinPeerTube host parsing.

ADR conflicts: none

## 2026-09-26 - Step 9 - Update documentation

- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md step 2 "Notes:" now has a bullet on how `sync-whitelist.py` turns whitelist entries into hosts through `normalize_host_token`.
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: UPDATER_WORKER.md now explains how `--sync-join-whitelist` normalises hosts, when it purges stale hosts, and the `--yes`/`--dry-run` flags that control that.
- [x] `docs/project/issues/06-normalise-instance-hosts.md` - updated: Issue 06 is marked delivered: status is `bug, complete`, five of the six acceptance criteria are ticked, and a delivery comment is added. The file has not been moved to `archive/` yet because I have no tool that can move or delete files.
- [x] `docs/project/plans/10-normalise-instance-hosts.md` - updated: I marked plan 10 as delivered, pointed it at build plan 16, and added a "Delivery" section recording what the build settled and three corrections to the plan's reading of the code. I did not move the file to `plans/archive/`, because I have no tool that can move files.
- [x] `docs/project/roadmap.md` - updated: Roadmap: issue 06 moved to Delivered, dropped from the open-security lists, and three host-normalisation follow-ups added under M6.
- [x] `DEPLOYMENT.md` - out of scope: It mentions `sync-whitelist.py` only in the run-order warning on line 43: run it after `crawl:videos` completes. It says nothing about how hosts-list entries are parsed or normalised, and that ordering is unchanged.
- [x] `README.md` - out of scope: Line 14 says only that filtering keeps instances that appear in the JoinPeerTube whitelist. That is still true, and the README makes no claim about entry spelling.
- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - out of scope: It describes the smoke test's inputs (`test-instances.json` or prod rows) and flow, and makes no claim about host normalisation or which fetch function is used. Its plain lowercase hosts pass through `normalize_host_token` unchanged, so nothing it says has become false.
- [x] `docs/project/security-audit/run-2/REPORT.md` - out of scope: This is a point-in-time audit record, not living documentation. Its line saying the moderation layer normalises hosts through `normalize_host` before comparing or deleting is still true: purges and serving filters still use `normalize_host`. The finding SI4-M1 is closed through the issue file, not by editing the report.
- [x] `docs/project/adr/0001-derived-interaction-event-ids.md` - out of scope: It covers interaction event ids. It does not touch host normalisation or the whitelist jobs. The same holds for ADRs 0002 (trusted proxy client address), 0003 (metadata endpoint uuid entries), 0004 (CORS) and 0005 (raw event retention). None of them makes a claim about JoinPeerTube host parsing.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** none

**ADR conflicts.** none

### `DATA_BUILD.md`

<changes>
DATA_BUILD.md step 2 "Notes:" now has a bullet on how `sync-whitelist.py` turns whitelist entries into hosts through `normalize_host_token`.

- The new bullet sits after the `--mode exclude` line. It says every entry goes through `data.moderation.normalize_host_token`, a port of the crawler's `normalizeHostToken`, so the job stores the same spelling the crawler does.
- It has three sub-bullets:
  - URL-like entries (`http://`, `https://`, or anything containing `/`) keep only the hostname, lowercased. Scheme, userinfo, port and path are dropped, IPv6 keeps its brackets, and internationalised names become punycode.
  - Bare entries are lowercased and only have leading and trailing dots trimmed, so a bare `host:port` keeps its port.
  - Entries that normalise to nothing (`""`, `.`, `https://`) are skipped, and the job fails with "Whitelist contained no hosts." when no entry is left.
- I checked each claim against the code: `normalize_host_token` and `_whatwg_hostname` in `engine/server/data/moderation.py`, and `fetch_hosts` in `engine/server/db/jobs/sync-whitelist.py`.
- The bullet describes only how things work today, with no "now" or "previously" wording. It says nothing about the updater, the fixture or the limitations, because other documents on this checklist cover those.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/db/jobs/docs/UPDATER_WORKER.md`

<changes>
UPDATER_WORKER.md now explains how `--sync-join-whitelist` normalises hosts, when it purges stale hosts, and the `--yes`/`--dry-run` flags that control that.

I checked each claim against `updater-worker.py` (the argparse block, `fetch_join_hosts`, `list_prod_hosts`, `purge_hosts` and the sync block in the main run).

- **"What Exactly Is Collected"**: the Instances bullet now has sub-bullets.
  - **Default mode:** `instances-cli` reads `--whitelist-url` itself.
  - **With `--sync-join-whitelist`:** `fetch_join_hosts` sends each entry through `data.moderation.normalize_host_token`, which gives the same spelling as the crawler's `normalizeHostToken`. Entries that normalise to nothing (`""`, `.`, `https://`) are dropped and denylisted hosts are removed. What remains is compared with the prod `instances` hosts: new hosts are crawled through `instances-cli --whitelist-file`, and prod hosts not on the list are stale.
  - **Purge:** stale hosts are purged from the prod and similarity DBs only with `--yes`. If stale hosts exist and `--yes` is missing, the worker refuses to run. `--dry-run` logs the stale hosts and the delete plan, then exits without changing anything.
  - **Old spellings:** prod hosts are only trimmed and lowercased before the comparison (`list_prod_hosts`). So an `instances` row stored in a spelling the crawler never produces (a scheme, trailing dots) counts as stale and `--yes` purges it. Operators should review with `--dry-run` first. This is written as current behaviour, with no "previously" wording.
- **"Important Flags"**: added `--sync-join-whitelist`, `--yes` and `--dry-run`, each with a short description based on its argparse help.

I left one existing inaccuracy alone because it is outside this build's scope: step 3 of "Execution Order" says staging is seeded from prod unless `--resume-staging` is used, but the code also skips seeding under `--sync-join-whitelist`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/06-normalise-instance-hosts.md`

<changes>
Issue 06 is marked delivered: status is `bug, complete`, five of the six acceptance criteria are ticked, and a delivery comment is added. The file has not been moved to `archive/` yet because I have no tool that can move or delete files.

- **Status line:** `Status: bug, ready-for-agent` is now `Status: bug, complete`.
- **Acceptance criteria:** I ticked the five that `tests/active/test_host_normalisation.py` covers:
  - the table-driven port test;
  - the node check of the crawler's compiled `dist/host-filters.js` over `host_tokens.json`;
  - the sync job storing one spelling per host;
  - entries that normalise to None being dropped;
  - `fetch_join_hosts` returning the same set as `fetch_hosts`.
- **Criterion left open:** "Existing moderation-integration and orchestrator smoke tests pass" stays unticked. The build never ran those two scripts, and the test-output files record no run of them either.
- **Delivery comment:** added under `## Comments`, after the triage comment. It records:
  - it links to the archived plan `docs/project/plans/archive/10-normalise-instance-hosts.md` and the build plan `docs/project/plans/16-10-normalise-instance-hosts.md`;
  - the helper is `normalize_host_token` in `engine/server/data/moderation.py`, right after the unchanged `normalize_host`, with the private `_whatwg_hostname` handling URL-form entries, and both jobs switched from `strip().lower()` to it;
  - the test file and its fixture, which holds the 14 required inputs plus `https://tube.example./` → `tube.example.`;
  - the stale-build rule: a missing node, dist or git fails the test and never skips it. It compares git commit times, and falls back to file times when a file has uncommitted edits or no commit;
  - that the two standalone scripts and the full `validate_tests.py` comparison against the baseline are still owed;
  - the six accepted limitations. I checked each against `moderation.py`, the `rat-tail` comment and `host-filters.ts`, where `loadHostsFromFile` sends every line through `normalizeHostToken`.
- **Still to do at harvest:**
  - Move the file to `docs/project/issues/archive/06-normalise-instance-hosts.md`, as `docs/project/issue-tracker.md` requires. Use `git mv`, from an agent that has a shell.
  - The comment's link assumes plan 10 is moved to `plans/archive/`, which that plan's own checklist item asks for.
  - Tick the last criterion only once both standalone scripts pass.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/plans/10-normalise-instance-hosts.md`

<changes>
I marked plan 10 as delivered, pointed it at build plan 16, and added a "Delivery" section recording what the build settled and three corrections to the plan's reading of the code. I did not move the file to `plans/archive/`, because I have no tool that can move files.

- **Status line** (new, under the title): says the plan is delivered by `docs/project/plans/16-10-normalise-instance-hosts.md` (wave 1). It points to the issue for the accepted limitations and the checks still owed, and does not repeat them.
  - The issue link uses the archive path `docs/project/issues/archive/06-normalise-instance-hosts.md`. That matches the issue's own delivery comment, which links to this plan at `plans/archive/`. Both links only work once harvest moves both files.
- **Risks and limitations:** the dist bullet no longer says "the build chooses which at its checkpoint". It now says the test fails loudly, never skips and never builds, and points to "Delivery".
- **New "Delivery" section.** Every claim was checked against the code:
  - **What the build settled:**
    - The fixture has 15 pairs, not 14. `https://tube.example./` → `tube.example.` was added, and I confirmed it in `tests/active/host_tokens.json`.
    - The test fails loudly instead of building first. It fails, and never skips, when node, dist or git is missing or dist is stale. The staleness check compares git commit times; I confirmed this in `_dist_is_stale` and `test_crawler_dist_returns_pinned_values`. The rest of the rule is left to the issue, which owns it.
  - **Corrections:**
    - The smoke test reaches `fetch_join_hosts` through `updater-worker.py --whitelist-url`, not `fetch_hosts`. I checked this in `test-orchestrator-smoke.py` (lines 421 and 440) and at `updater-worker.py:831`.
    - Only `sync-whitelist.py` parses `schema.sql` when it is imported. The updater reads it inside `main()` (line 789).
    - When the crawler reads back the `--whitelist-file` hosts, it strips a trailing dot from URL-form hosts. I checked this against `loadHostsFromFile` in `host-filters.ts` and `updater-worker.py` lines 894–916. This section links to the roadmap for the follow-up.
- **Not in this file:** the checklist asks me to fix a sentence in the "Requirement: existing scripts and suite still pass" paragraph, the one saying the smoke test "serves `whitelist.json` through `fetch_hosts`". That sentence is not in plan 10. It is at line 164 of the build plan `docs/project/plans/16-10-normalise-instance-hosts.md`, which is not on the checklist, and I left it unchanged. Plan 10 now carries the correct fact under "Corrections".
- **Still to do at harvest:** `git mv` this file to `docs/project/plans/archive/10-normalise-instance-hosts.md`, as is done for delivered plans.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/roadmap.md`

<changes>
Roadmap: issue 06 moved to Delivered, dropped from the open-security lists, and three host-normalisation follow-ups added under M6.

- **Delivered**: a new line for security issue `06`. `sync-whitelist.py` and the updater's `fetch_join_hosts` both pass every hosts-list entry through `data.moderation.normalize_host_token`, a port of the crawler's `normalizeHostToken`. The line points at `docs/project/plans/archive/10-normalise-instance-hosts.md`, where harvest moves the plan.
- **M1**: "Open security issues" now reads `01` to `05` and `07`.
- **Implementation order, step 1**: now reads `01`, `02`, `03`, then `04`, `05`. Issue `06` is no longer listed.
- **M6**: three follow-up lines, each checked against the code:
  - Move `compare-join-hosts.py` onto `normalize_host_token`. Its `hosts_from_payload` (line 80) and `load_local_hosts` (line 96) still use `strip().lower()`.
  - Make the crawler's `--whitelist-file` mode (`loadHostsFromFile`, `host-filters.ts:10`, which calls `normalizeHostToken`) agree with URL mode on trailing dots.
  - Optionally, align `normalize_host` (denylist input) on bracketed IPv6 and punycode.
</changes>

<not_on_checklist>
none
</not_on_checklist>

