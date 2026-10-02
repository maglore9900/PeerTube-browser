"""The About page in production: DEPLOYMENT.md §6's nginx site block, run in a real nginx, serves it and writes its visit log, and the "Follow an About visit" runbook reads that log.

- Serving: `nginx -t` accepts the block. For GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with the dev-pages override (alone or beside the template) the answer is 200 with the override's bytes and Content-Length; with only the template, 200 with the template's; with neither, 404. Each answer has exactly one Content-Security-Policy header, equal to the block's. /aboutx, /about/x and /about.htm stay 404 with the CSP.
- Mapping: the block's `location =` URLs are vite.config.ts's rewriteToAbout, once each, and each one's try_files candidates before the fallback are aboutSourcePath's two picks, the override first.
- Pages log: GET and HEAD on those About URLs, with and without an X-Request-ID header, answered 200 from the template or 404 with no dev-pages files, each write one line to peertube-browser.pages.access.log and one to peertube-browser.access.log. The pages line's first eight fields are page=about, ts=<digits.3 digits>, time=<ISO 8601>, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>; after them uri= is the requested path plus query, x_request_id= the sent header or -, ua= the sent User-Agent. The main line is that request's usual line and carries the same request_id. /, /index.html, /api/health (502, upstream refused), /dev-pages/about.html and /dev-pages/about.template.html each write one main line and no pages line, in a run where an About request does write one.
- Runbook listing: a GET /about.html (200), a HEAD /about (200) and a GET /about/ answered 404 whose User-Agent carries ` status=200 method=GET page=about ` and, in the real field order, ` method=GET status=200 rt=0.000 ` each write a pages line; the forged one keeps `status=404` as its sixth field, and every runbook line that filters the pages log for GET and 200 prints exactly the real GET line.
- Runbook correlation: with a pages log of three visits and Client request.start/request.end records rendered by the real ClientLogFormatter, the runbook, given the visit's request_id, prints exactly the record from the visit's address 10 s after it, in JSON and in text: not the one 5 s before, the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45.

The block is the first ```nginx fence after the sites-available line. Its root, log directory, `listen 80` and upstream port are swapped for tmp paths, a free loopback port and a refused one, and it is wrapped in a minimal http{} with tmp temp paths. The runbook is every ```bash fence between `### Follow an About visit` and the next heading, run under bash with `/var/log/nginx/` swapped for a tmp directory, `sudo` running its command, `journalctl` printing the tmp Client log, TZ five hours behind UTC, and only text tools on PATH; its one `name=<…>` placeholder line gets the visit's request_id, and a missing section is an empty runbook, which fails at the claim assertions. Tests skip when nginx is missing or will not run unprivileged, or when bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing.
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
VITE_CONFIG = ROOT / "client" / "frontend" / "vite.config.ts"
TEMPLATE = ROOT / "client" / "frontend" / "dev-pages" / "about.template.html"
BACKEND_DIR = ROOT / "client" / "backend"
NGINX = shutil.which("nginx")
BASH = shutil.which("bash")
SITE_LINE = "`/etc/nginx/sites-available/peertube-browser`:"
RUNBOOK_HEADING = "### Follow an About visit"
# What keeps the block from running unprivileged or reaching a live backend: the document root, the log directory, port 80 and the Client backend's port.
SWAPS = (("root /var/www/peertube-browser;", "root {www};"), ("/var/log/nginx/", "{log}/"), ("listen 80;", "listen 127.0.0.1:{port};"), ("127.0.0.1:7072", "127.0.0.1:{upstream}"))
ABOUT_URLS = ("/about", "/about/", "/about.html", "/about.html?x=1")
# Not About under exact locations: they fall to `location /`, where no such file exists.
NOT_ABOUT_URLS = ("/aboutx", "/about/x", "/about.htm")
OTHER_ROUTES = {"/": 200, "/index.html": 200, "/api/health": 502, "/dev-pages/about.html": 200, "/dev-pages/about.template.html": 200}
OVERRIDE = b"<!doctype html><title>dev-pages override</title>\n"
INDEX = b"<!doctype html><title>index</title>\n"
# Not 32 hex digits, so a request_id copied from the header cannot pass for nginx's own.
SENT_ID = "client-sent-7"
AGENT = "probe-agent/1"
PAGES_HEAD = re.compile(r"page=about ts=\d+\.\d{3} time=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d ip=127\.0\.0\.1 method=(\S+) status=(\S+) rt=\d+\.\d{3} request_id=([0-9a-f]{32})")
# The runbook's commands get these and nothing else, so an installer line that falls inside the section cannot run.
TOOLS = ("awk", "grep", "cat", "jq", "date", "sed", "cut", "tr", "head", "tail", "sort")
# Prefixed: nginx strips a header value's leading space, which would glue the first forged token to `ua="` (observed). The second run repeats the real field order, so a filter that matches a contiguous ` method=GET status=200 rt=` rather than reading fields 5 and 6 lists this 404.
FORGED_UA = "forger/1 status=200 method=GET page=about method=GET status=200 rt=0.000 forger/1"
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


def _statements(nginx_text: str) -> list[str]:
    """nginx directives with comments dropped and whitespace collapsed, so a second `listen` on any line or inside a block is counted."""
    text = re.sub(r"#[^\n]*", "", nginx_text)
    return [" ".join(part.split()) for part in re.split(r"[;{}]", text) if part.strip()]


def _csp(block: str) -> str:
    match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', block)
    assert match, "no Content-Security-Policy add_header in the block"
    return match.group(1)


def _runbook() -> list[str]:
    """The ```bash fences between the runbook heading and the next heading outside a fence, backslash-continued lines joined; none when the heading is absent."""
    lines = DEPLOYMENT.read_text(encoding="utf-8").splitlines()
    # An absent section is an empty runbook, so the tests reach their claim assertions and fail there rather than in setup.
    if RUNBOOK_HEADING not in lines:
        return []
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
    """Writes www (index.html plus the given dev-pages files) and the swapped, wrapped §6 block, checks that `nginx -t` accepts it, and returns the run directory and the listen port."""
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
    assert check.returncode == 0, check.stderr  # the block as published loads
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


def _answer(port: int, method: str, url: str) -> tuple[int, list[str], str | None, bytes]:
    """Status, every Content-Security-Policy value, Content-Length and body; http.client follows no redirect, so a 301 shows as one."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, url)
        resp = conn.getresponse()
        return resp.status, [value for name, value in resp.getheaders() if name.lower() == "content-security-policy"], resp.getheader("Content-Length"), resp.read()
    finally:
        conn.close()


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
    """A pages-log line as §6's peertube_browser_pages writes it (the format the pages-log test pins), for a GET /about.html answered 200 on a host five hours behind UTC."""
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


@pytest.mark.parametrize(("present", "served"), [pytest.param(("about.html", "about.template.html"), "about.html", id="override-and-template"), pytest.param(("about.html",), "about.html", id="override-only"), pytest.param(("about.template.html",), "about.template.html", id="template-only"), pytest.param((), None, id="neither")])
def test_about_urls_serve_override_then_template_then_404_with_csp(tmp_path: Path, present: tuple[str, ...], served: str | None) -> None:
    """`nginx -t` accepts the §6 block; GET and HEAD on /about, /about/, /about.html and /about.html?x=1 answer 200 with the override's bytes and length when it exists, else the template's, else 404, each with exactly one CSP header equal to the block's; /aboutx, /about/x and /about.htm answer 404 with the CSP."""
    _require_unprivileged_nginx(tmp_path)
    csp = _csp(_site_block())
    files = {"about.html": OVERRIDE, "about.template.html": TEMPLATE.read_bytes()}
    assert len(files["about.html"]) != len(files["about.template.html"])  # control: override and template differ in Content-Length, so HEAD tells them apart too
    run_dir, port = _configure(tmp_path, {name: files[name] for name in present})

    with _serving(run_dir, port):
        assert _answer(port, "GET", "/") == (200, [csp], str(len(INDEX)), INDEX)  # control: the harness serves the block's root with the block's CSP
        got = {f"{method} {url}": _answer(port, method, url) for url in ABOUT_URLS for method in ("GET", "HEAD")}
        not_about = {f"GET {url}": _answer(port, "GET", url)[:2] for url in NOT_ABOUT_URLS}

    if served is None:
        assert {key: answer[:2] for key, answer in got.items()} == {key: (404, [csp]) for key in got}  # neither file is a 404, still carrying the CSP
    else:
        body = files[served]
        assert got == {f"{method} {url}": (200, [csp], str(len(body)), body if method == "GET" else b"") for url in ABOUT_URLS for method in ("GET", "HEAD")}  # override when present, else template; one CSP equal to the block's
    assert not_about == {f"GET {url}": (404, [csp]) for url in NOT_ABOUT_URLS}  # only the three exact URLs are About


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
    assert sorted(url for url, _ in exact) == sorted(urls)  # the exact locations are vite's About URLs, each once
    candidates = {url: [statement.split()[1:-1] for statement in _statements(body) if statement.split()[0] == "try_files"] for url, body in exact}
    assert candidates == {url: [picks] for url in urls}  # one try_files each, override then template, as aboutSourcePath picks


@pytest.mark.parametrize(("present", "code"), [pytest.param(("about.template.html",), 200, id="template-200"), pytest.param((), 404, id="no-files-404")])
def test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id(tmp_path: Path, present: tuple[str, ...], code: int) -> None:
    """GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with and without X-Request-ID, answered 200 or 404: each adds one pages line (page=about, ts, ISO time, ip=127.0.0.1, method, status, rt, 32-hex request_id, then the requested uri, the sent X-Request-ID or -, the sent UA) and one main line for that request carrying the same request_id."""
    _require_unprivileged_nginx(tmp_path)
    run_dir, port = _configure(tmp_path, {name: TEMPLATE.read_bytes() for name in present})
    requests = [(method, url, sent) for url in ABOUT_URLS for method in ("GET", "HEAD") for sent in (None, SENT_ID)]
    with _serving(run_dir, port):
        got = {(method, url, sent): _request(run_dir, port, method, url, {"User-Agent": AGENT, **({"X-Request-ID": sent} if sent else {})}) for method, url, sent in requests}

    assert {key: (status, len(main), len(pages)) for key, (status, main, pages) in got.items()} == {key: (code, 1, 1) for key in requests}  # one main line and one pages line per About request, at 200 and at 404
    records = {key: _record(pages[0], main[0]) for key, (_, main, pages) in got.items()}
    assert records == {(method, url, sent): {"head": (method, str(code)), "uri": url, "x_request_id": sent or "-", "ua": AGENT, "main": (f"{method} {url} HTTP/1.1", str(code)), "same_request_id": True} for method, url, sent in requests}  # fields 1-8 fixed, uri as requested, x_request_id sent or -, and the main line of the same request shares the request_id


def test_other_routes_write_no_pages_line(tmp_path: Path) -> None:
    """In one run, GET /about.html writes one pages line while /, /index.html, /api/health (502), /dev-pages/about.html and /dev-pages/about.template.html each write none; every one of them writes one main line for that request."""
    _require_unprivileged_nginx(tmp_path)
    run_dir, port = _configure(tmp_path, {"about.html": OVERRIDE, "about.template.html": TEMPLATE.read_bytes()})
    # About's row is the contrast: a pages log nothing writes, or one every route writes, both fail the same comparison.
    routes = {"/about.html": (200, 1), **{url: (code, 0) for url, code in OTHER_ROUTES.items()}}
    with _serving(run_dir, port):
        got = {url: _request(run_dir, port, "GET", url, {}) for url in routes}

    assert {url: (status, [_main_request(line) for line in main], len(pages)) for url, (status, main, pages) in got.items()} == {url: (code, [(f"GET {url} HTTP/1.1", str(code))], pages) for url, (code, pages) in routes.items()}  # About writes one pages line and every other route none, each with one main line for that request


def test_forged_user_agent_does_not_move_fields(tmp_path: Path) -> None:
    """A GET /about/ answered 404 whose User-Agent carries space-delimited status=200, method=GET and page=about tokens, once reversed and once in the real `method=GET status=200 rt=` order, keeps status=404 as its pages line's sixth field, and every runbook line filtering the pages log for GET and 200 prints only the real GET /about.html 200 line, not that one nor a HEAD /about 200."""
    _require_tools("awk", "grep", "cat")
    _require_unprivileged_nginx(tmp_path)
    run_dir, port = _configure(tmp_path, {"about.template.html": TEMPLATE.read_bytes()})
    with _serving(run_dir, port):
        get = _request(run_dir, port, "GET", "/about.html", {"User-Agent": AGENT})
        head = _request(run_dir, port, "HEAD", "/about", {"User-Agent": AGENT})
        (run_dir / "www" / "dev-pages" / "about.template.html").unlink()
        forged = _request(run_dir, port, "GET", "/about/", {"User-Agent": FORGED_UA})
    assert [(status, len(pages)) for status, _, pages in (get, head, forged)] == [(200, 1), (200, 1), (404, 1)]  # control: one pages line each, the forged one a 404
    forged_line = forged[2][0]
    assert " status=200 method=GET page=about " in forged_line and " method=GET status=200 rt=0.000 " in forged_line, forged_line  # control: the forged tokens reached the log space-delimited, so a substring grep for ' status=200 ', ' method=GET ' or the real order ' method=GET status=200 rt=' matches this 404

    assert forged_line.split()[5] == "status=404", forged_line  # control: the field a positional filter reads is not moved by the forged tokens

    filters = [line for block in _runbook() for line in block.splitlines() if "peertube-browser.pages.access.log" in line and "GET" in line and "200" in line and not line.lstrip().startswith("#")]
    listed = {line: _bash(tmp_path, run_dir / "log", line) for line in filters}
    # A runbook with no such filter reads {} against the placeholder key, so it fails here too.
    assert {line: run.stdout.splitlines() for line, run in listed.items()} == {line: get[2] for line in filters or ["<a runbook line filtering the pages log for GET and 200>"]}, {line: run.stderr for line, run in listed.items()}


def test_runbook_finds_visit_and_client_record(tmp_path: Path) -> None:
    """Given the visit's request_id, the runbook prints exactly the Client request.start record from the visit's address 10 s after it, in JSON and in text: not the one 5 s before, the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45 (the address of a later visit in the same pages log)."""
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
    # The 5 s-before record is what makes the window open at the visit: any window reaching back 5 s takes it, and a symmetric one must, since it covers +10 s.
    starts = {"just_before": (-5, VISIT_IP), "before": (-60, VISIT_IP), "match": (10, VISIT_IP), "neighbour": (20, NEIGHBOUR_IP), "late": (3600, VISIT_IP)}
    records = []
    for name, (offset, ip) in starts.items():
        created = VISIT_MS / 1000 + offset
        records.append([created, "request.start", "request started", f"rid-{name}", {"ip": ip, "method": "GET", "url": "http://127.0.0.1:7072/api/videos", "user_agent": "Mozilla/5.0 (X11; Linux x86_64)"}])
        records.append([created + 0.05, "request.end", "request finished", f"rid-{name}", {"status": 200, "duration_ms": 50}])

    runbook = _runbook()
    script, placeholders = re.subn(r"^(\w+)=<[^<>\n]+>$", rf"\g<1>={VISIT_ID}", "\n".join(runbook), flags=re.M)
    assert placeholders == 1 or not runbook, f"expected one `name=<…>` line for the visit's request_id, found {placeholders}"  # control: a runbook's only input is the visit's id; an absent one runs empty and fails below

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

    assert got["json"] == expected["json"], stderr["json"]
    assert got["text"] == expected["text"], stderr["text"]
