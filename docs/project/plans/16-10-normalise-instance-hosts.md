# 10-normalise-instance-hosts

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/16-10-normalise-instance-hosts.record.md`._

## Requirements

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

## High-level plan

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

## Impacts


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


## Documentation to update

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

## Implementation plan

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

### Phases

#### Phase 1 - Python port of normalizeHostToken [code]

**Files touched.** engine/server/data/moderation.py (EDITED), tests/active/host_tokens.json (NEW), tests/active/test_host_normalisation.py (NEW)

**Checkpoint.** Seam: the pure function `data.moderation.normalize_host_token`, called directly from pytest with `engine/server` added to sys.path, following test_db.py:22-26 (`SERVER_DIR` insert plus a `# noqa: E402` import) and `ROOT` from conftest as test_similar.py uses it. The test is parametrised over the pairs loaded at run time from `tests/active/host_tokens.json` (15 pairs, with ids from repr(input)). It asserts `normalize_host_token(input) == expected`, with JSON null standing for None. Together the pairs exercise all four branches, userinfo, port drop, port keep in branch 4, IPv6 re-bracketing, punycode, the None cases and dot keeping in URL form. It runs in the normal validate_tests.py pass because it uses no Engine fixture.

**Intent.** `engine/server/data/moderation.py` gains `normalize_host_token`, placed directly after the unchanged `normalize_host`, and it returns the pinned value for every pair in `tests/active/host_tokens.json`.

- C1 - `normalize_host_token` returns each fixture pair's expected value, and None where the expected value is null.

**Outcome.** Nothing needed writing this turn. All three files in this phase were already in the worktree when the turn started. I checked each against the crawler source and the checkpoint's pinned values, and left them unchanged. I did not write them in this turn, so they came from an earlier pass over this step.

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

#### Phase 2 - Crawler parity and loud failure [code]

**Files touched.** tests/active/test_host_normalisation.py (EDITED)

**Checkpoint.** Seam, clause 1: the crawler's compiled module `engine/crawler/dist/host-filters.js`, entered by one `node --input-type=module -e` subprocess. The subprocess imports that module by its file:// URL (passed in the HOST_FILTERS_URL env var), reads the fixture inputs as JSON on stdin and prints `normalizeHostToken` of each as JSON. The test asserts returncode 0 and that dict(zip(inputs, outputs)) equals the pinned {input: expected} map. Because phase 1 checks Python against the same map, passing this proves Python == crawler on the fixture. Seam, clause 2: the pytest outcome of the node test itself. The checkpoint runs `python -m pytest tests/active/test_host_normalisation.py -k crawler_dist` in a subprocess three times: with a PATH that lacks node, with DIST pointed at a missing path, and with a stale dist. It asserts each run reports failed, not skipped, and that the message names the build hint. The staleness rule is settled here: compare the git commit times of src/host-filters.ts and dist/host-filters.js; fall back to mtime when src has uncommitted changes or either file has no history; a missing git is a failure.

**Intent.** `test_host_normalisation.py` checks the crawler's compiled `normalizeHostToken` against the same pinned fixture, and the check cannot pass without node and a current `dist/host-filters.js`.

- C1 - `dist/host-filters.js` run under node returns each fixture pair's expected value.
- C2 - A missing node, a missing dist or a stale dist makes the crawler test fail rather than skip.

**Outcome.** ### `tests/active/test_host_normalisation.py`
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

**Beyond the files named.** tests/tmp/probe_git_outside_worktree.py — the probe I used to check git behaviour and the junit message before writing the test. It now holds only a docstring (no tests) because I had no delete tool; please delete it.

#### Phase 3 - Both jobs normalise through the helper [code]

**Files touched.** engine/server/db/jobs/sync-whitelist.py (EDITED), engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_host_normalisation.py (EDITED)

**Checkpoint.** Seam: the two jobs' fetch functions and `sync_hosts`. Both job files are loaded with importlib.util.spec_from_file_location, following the test_similar.py:36-41 precedent, in a module-scoped fixture. Payloads are served from tmp_path as file:// URIs, so no server and no network are needed. Clause 1: a list-shape payload ["https://Tube.Example/", "tube.example"] gives {"tube.example"} from `fetch_hosts`. `ensure_whitelist_schema` plus `sync_hosts` into a tmp_path SQLite file (never the shared whitelist.db) returns (1, 0, 1) and stores exactly the one row "tube.example". Clause 2: a dict-shape payload mixing "", "   ", ".", "https://" with valid entries gives {"tube.example", "other.example"} from both `fetch_hosts` and `fetch_join_hosts`. Regression guard, not a new clause: `fetch_hosts` on a payload where every entry normalises to None still raises ValueError "Whitelist contained no hosts.". After the phase, run test-moderation-integration.py, test-orchestrator-smoke.py (report it as not run if node, dist, the embedding stack or network is missing) and validate_tests.py from the worktree, compared with the green baseline.

**Intent.** `fetch_hosts` in sync-whitelist.py and `fetch_join_hosts` in updater-worker.py pass every hosts-list entry through `normalize_host_token` in place of `strip().lower()`.

- C1 - `fetch_hosts` collapses `https://Tube.Example/` and `tube.example` to the single host `tube.example`, which `sync_hosts` stores as one row.
- C2 - Entries that normalise to None are dropped, and `fetch_join_hosts` returns the same host set as `fetch_hosts`.

**Outcome.** ### `engine/server/db/jobs/sync-whitelist.py`
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


