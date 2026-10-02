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
    """In one run, GET /about.html writes one pages line while /, /index.html, /api/health (502), /dev-pages/about.html and /dev-pages/about.template.html each write none; every one of them writes one main line for that request."""
    _require_unprivileged_nginx(tmp_path)
    run_dir, port = _configure(tmp_path, {"about.html": OVERRIDE, "about.template.html": TEMPLATE.read_bytes()})
    # About's row is the contrast: a pages log nothing writes, or one every route writes, both fail the same comparison.
    routes = {"/about.html": (200, 1), **{url: (code, 0) for url, code in OTHER_ROUTES.items()}}
    with _serving(run_dir, port):
        got = {url: _request(run_dir, port, "GET", url, {}) for url in routes}

    assert {url: (status, [_main_request(line) for line in main], len(pages)) for url, (status, main, pages) in got.items()} == {url: (code, [(f"GET {url} HTTP/1.1", str(code))], pages) for url, (code, pages) in routes.items()}  # C2: About writes one pages line and every other route none, each with one main line for that request
