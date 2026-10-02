"""The About beacon module in node, and the About page as vite builds it.

- Bundled by the project's esbuild with `VITE_CLIENT_API_BASE` "http://api.test/" and run in node under a browser-shaped global (window is globalThis, a stubbed `location`, `document`, `navigator` and a rejecting `fetch`, `Date.now` fixed), importing `src/about-analytics.ts` and then clicking an untracked link, a Text-like target, a span inside an `a[data-track-id="about_patreon"]`, an `a[data-track-id="about_github"]` and the patreon span again sends exactly four events to `http://api.test/api/analytics/event`: first `{type: page_view, page_path, timestamp}`, then one `{type: outbound_click, track_id, href, page_path, timestamp}` per tracked click carrying that link's own id and href (patreon, github, patreon), with nothing else in any body and `page_path` the stubbed `location.pathname` (`/about` or `/about.html` by mode). With `sendBeacon` returning true all go as `application/json` Blob beacons and `fetch` is never called; with it returning false or throwing, each is first offered to the bound `navigator.sendBeacon` and then posted by `fetch`, in that order per event, with `keepalive: true` and `Content-Type: application/json`, as they are when `sendBeacon` is missing. In every mode exactly one `click` listener is on `document`, no handler throws, no default is prevented and no rejection goes unhandled.
- A real `vite build` into a tmp outDir writes `dev-pages/about.template.html` with a `/assets/*.js` script whose file contains `/api/analytics/event`; skipped when a local `dev-pages/about.html` override would be built instead.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
VITE = FRONTEND / "node_modules" / ".bin" / "vite"
MODULE = FRONTEND / "src" / "about-analytics.ts"
# Trailing slash on purpose: plain concatenation would give `//api`.
API_BASE = "http://api.test/"
EVENT_URL = "http://api.test/api/analytics/event"
# The page's own origin differs from the API base, so a URL built from `window.location.origin` shows.
PAGE_ORIGIN = "http://page.test"
NOW = 1700000000123
TRACKED_HREF = "https://www.patreon.com/x"
OTHER_HREF = "https://github.com/y"
# Transport attempts per event, in order, by sendBeacon mode.
TRANSPORTS = {"true": ["beacon"], "false": ["beacon", "fetch"], "missing": ["fetch"], "throws": ["beacon", "fetch"]}
# Both paths the About page is served at; the mode decides which, so a page_path hardcoded to "/about" shows.
PAGE_PATHS = {"true": "/about", "false": "/about.html", "missing": "/about", "throws": "/about.html"}

RUNNER = """
const MODE = process.env.MODE;
const NOW = Number(process.env.NOW);
// The clock is a system boundary: fixed, so the timestamp sent is known.
Date.now = () => NOW;
const sends = [];
const pending = [];
const errors = [];
const rejections = [];
const listeners = [];
// Every transport attempt in call order, including a refused or throwing beacon, so beacon-before-fetch is observable.
const calls = [];
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
const read = async (data) => (typeof data === "string" ? data : await data.text());
// Recorded in call order; the payload is read afterwards, since a Blob only reads asynchronously.
const record = (entry, data) => { sends.push(entry); pending.push(read(data).then((body) => { entry.body = body; })); };
const nav = { userAgent: "node-runner" };
if (MODE !== "missing") {
  nav.sendBeacon = function (url, data) {
    // A browser throws "Illegal invocation" on a sendBeacon detached from its navigator; the stub does too.
    if (this !== nav) throw new TypeError("Illegal invocation");
    calls.push("beacon");
    if (MODE === "throws") throw new TypeError("beacon refused");
    if (MODE === "false") return false;
    record({ via: "beacon", url: String(url), blobType: data?.type ?? null }, data);
    return true;
  };
}
// Node 22's navigator is a getter-only global: assignment throws, defineProperty replaces it.
Object.defineProperty(globalThis, "navigator", { value: nav, configurable: true, writable: true });
const contentType = (headers) => (headers instanceof Headers ? headers.get("content-type") : Object.entries(headers ?? {}).find(([name]) => name.toLowerCase() === "content-type")?.[1] ?? null);
globalThis.fetch = (url, init = {}) => {
  calls.push("fetch");
  record({ via: "fetch", url: String(url), method: init.method ?? "GET", keepalive: init.keepalive ?? false, contentType: contentType(init.headers) }, init.body ?? "");
  return Promise.reject(new TypeError("offline"));
};
globalThis.location = { origin: process.env.PAGE_ORIGIN, pathname: process.env.PAGE_PATH, href: process.env.PAGE_ORIGIN + process.env.PAGE_PATH };
globalThis.document = { nodeType: 9, addEventListener: (type, listener) => { listeners.push({ type, listener }); }, removeEventListener() {} };
globalThis.window = globalThis;
const element = (tag, attrs, parent) => {
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), parentElement: parent, href: attrs.href,
    dataset: "data-track-id" in attrs ? { trackId: attrs["data-track-id"] } : {},
    getAttribute: (name) => attrs[name] ?? null, hasAttribute: (name) => name in attrs,
    matches: (selector) => {
      const m = /^([a-z]+)?(?:\\[([a-z-]+)\\])?$/.exec(selector);
      if (!m || (!m[1] && !m[2])) throw new Error(`runner stub matches only tag and [attribute] selectors, got ${selector}`);
      return (!m[1] || m[1] === tag) && (!m[2] || m[2] in attrs);
    },
    closest: (selector) => { for (let node = el; node; node = node.parentElement) if (node.matches(selector)) return node; return null; },
  };
  return el;
};
await import(process.env.BUNDLE);
const body = element("body", {}, null);
const tracked = element("a", { href: process.env.TRACKED_HREF, "data-track-id": "about_patreon" }, body);
const other = element("a", { href: process.env.OTHER_HREF, "data-track-id": "about_github" }, body);
// An untracked link, a Text-like node without `closest`, a span inside the tracked link so only a `closest` walk finds it, a second tracked link with its own id and href, then the first tracked link again, so a once-per-page or once-per-id send shows.
const targets = [element("a", { href: "https://example.org/untracked" }, body), { nodeType: 3, textContent: "Patreon", parentElement: null }, element("span", {}, tracked), other, element("span", {}, tracked)];
const prevented = [];
for (const target of targets) {
  const event = { type: "click", target, currentTarget: globalThis.document, button: 0, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; } };
  for (const { type, listener } of listeners) {
    if (type !== "click") continue;
    try { typeof listener === "function" ? listener.call(globalThis.document, event) : listener.handleEvent(event); } catch (error) { errors.push(String(error)); }
  }
  prevented.push(event.defaultPrevented);
}
const settle = async () => { for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
await settle();
await Promise.all(pending);
// unhandledRejection is reported a tick after the rejection, so the count is read only once timers have run.
await settle();
process.stdout.write(JSON.stringify({ sends, calls, listeners: listeners.map(({ type }) => type), errors, rejections, prevented }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def runner(tmp_path_factory) -> Path:
    """The module bundled for node as `test_frontend_profile.py` bundles its modules, beside the runner script."""
    tmp_path = tmp_path_factory.mktemp("about_beacon")
    bundle = tmp_path / "bundle.mjs"
    result = subprocess.run(
        [str(ESBUILD), str(MODULE), "--bundle", "--format=esm", "--platform=node", f"--outfile={bundle}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(API_BASE)}",
         "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    script = tmp_path / "runner.mjs"
    script.write_text(RUNNER)
    return script


def _run(runner: Path, mode: str) -> dict:
    """Import the bundle under sendBeacon `mode` at that mode's page path, click the five targets, and return what the runner observed."""
    result = subprocess.run(
        ["node", str(runner)], capture_output=True, text=True, timeout=60,
        env={"PATH": os.environ.get("PATH", ""), "BUNDLE": str(runner.parent / "bundle.mjs"), "MODE": mode,
             "NOW": str(NOW), "PAGE_ORIGIN": PAGE_ORIGIN, "PAGE_PATH": PAGE_PATHS[mode], "TRACKED_HREF": TRACKED_HREF, "OTHER_HREF": OTHER_HREF},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("mode", ["true", "false", "missing", "throws"])
def test_import_and_tracked_clicks_send_one_event_each_by_beacon_or_keepalive_fetch(runner: Path, mode: str) -> None:
    """One page_view on import and one outbound_click per tracked click, carrying the clicked link's own id and href, none for the untracked or Text-like target, to the API base's event URL; by beacon only when sendBeacon returns true, otherwise by keepalive JSON fetch after the bound sendBeacon was tried; one document click listener, no throw, no prevented default, no unhandled rejection."""
    report = _run(runner, mode)
    sends = report["sends"]
    page_path = PAGE_PATHS[mode]
    patreon = {"type": "outbound_click", "track_id": "about_patreon", "href": TRACKED_HREF, "page_path": page_path, "timestamp": NOW}
    github = {"type": "outbound_click", "track_id": "about_github", "href": OTHER_HREF, "page_path": page_path, "timestamp": NOW}
    assert [send["url"] for send in sends] == [EVENT_URL] * 4  # C1: exactly four sends, all to the Client API base's event route
    assert [json.loads(send["body"]) for send in sends] == [{"type": "page_view", "page_path": page_path, "timestamp": NOW}, patreon, github, patreon]  # C1: page_view on import, then one outbound_click per tracked click with that link's id and href, the repeated click sent again, each carrying the page's own path
    if mode == "true":
        assert [(send["via"], send.get("blobType")) for send in sends] == [("beacon", "application/json")] * 4  # C1: delivered by beacon, fetch never called
    else:
        assert [(send["via"], send.get("method"), send.get("keepalive"), send.get("contentType")) for send in sends] == [("fetch", "POST", True, "application/json")] * 4  # C1: keepalive fetch fallback
    assert report["calls"] == TRANSPORTS[mode] * 4  # C1: each event offered to the bound navigator.sendBeacon first when it exists, and fetched only after it
    assert report["listeners"] == ["click"]  # C1: one delegated click listener on document
    assert report["errors"] == []  # C1: the untracked and Text-like targets are handled without a throw
    assert report["rejections"] == []  # C1: the rejecting fetch never surfaces as an unhandled rejection
    assert report["prevented"] == [False] * 5  # regression line, not a clause: navigation is never prevented


def test_built_about_page_loads_a_bundled_asset_with_the_event_route(tmp_path: Path) -> None:
    """A real vite build writes the About template with a /assets/*.js script whose file contains /api/analytics/event."""
    if (FRONTEND / "dev-pages" / "about.html").exists():
        pytest.skip("a local dev-pages/about.html override exists; vite.config.ts builds it as the about input instead of the template")
    out = tmp_path / "dist"
    result = subprocess.run([str(VITE), "build", "--outDir", str(out), "--emptyOutDir"], cwd=FRONTEND, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    page = (out / "dev-pages" / "about.template.html").read_text()
    scripts = re.findall(r'<script\b[^>]*\bsrc="(/assets/[^"]+\.js)"', page)
    assert scripts, page  # C2: the built page loads a bundled asset
    assert any("/api/analytics/event" in (out / src.lstrip("/")).read_text() for src in scripts), scripts  # C2: one of them carries the event route
