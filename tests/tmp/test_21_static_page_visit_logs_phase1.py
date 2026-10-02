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
