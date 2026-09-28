"""The video page's similars, run in node with the real page module: its first batch is one `/recommendations` request for 48 rows, of which only the first 8 are shown.

- The page makes exactly one `/recommendations` request, a POST whose `limit` query parameter is "48" (the limit travels in the query string).
- Answered with 48 distinct rows in up-next mode, `#similar-videos` holds exactly 8 `similar-card-item` anchors, and they are the answer's first 8 rows in order.

The runner is the one in `tests/active/test_frontend_video_page.py`, plus an `IntersectionObserver` that never fires, a document taller than the window so filling the viewport never asks for more, and element markup that keeps what `insertAdjacentHTML` adds as well as what `innerHTML` sets. `fetch` records each request's method, path, query and JSON body, answers `/recommendations` with the 48 rows and `{}` elsewhere.
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
BASE = "http://client.test"
ROWS = 48
SHOWN = 8

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
// The document is far taller than the window and nothing has scrolled, so a fill-viewport pass never asks for another batch.
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: "?id=v1&host=peer.example" },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage, innerHeight: 800, scrollY: 0,
  addEventListener() {}, removeEventListener() {} };
const text = (value) => ({ nodeType: 3, textContent: String(value) });
const nodes = (items) => items.map((n) => (typeof n === "string" ? text(n) : n));
const element = (tag, hidden = false) => {
  const classes = new Set();
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), hidden, children: [], dataset: {}, style: {}, attrs: {}, parentElement: null,
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? (c.nodeType === 1 ? c.outerHTML : "")).join(""); },
    set innerHTML(v) { el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get outerHTML() { return `<${tag} class="${el.className}">${el.innerHTML}</${tag}>`; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c), toggle: (c, force) => { const on = force ?? !classes.has(c); if (on) classes.add(c); else classes.delete(c); return on; } },
    append: (...items) => { el.children.push(...nodes(items)); },
    appendChild: (child) => { el.children.push(child); return child; },
    replaceChildren: (...items) => { el.children = nodes(items); },
    setAttribute: (name, value) => { if (name === "hidden") el.hidden = true; else if (name === "class") el.className = value; else el.attrs[name] = String(value); },
    removeAttribute: (name) => { if (name === "hidden") el.hidden = false; else delete el.attrs[name]; },
    toggleAttribute: (name, force) => { const on = force ?? !(name === "hidden" ? el.hidden : name in el.attrs); el[on ? "setAttribute" : "removeAttribute"](name, ""); return on; },
    getAttribute: (name) => (name === "hidden" ? (el.hidden ? "" : null) : el.attrs[name] ?? null),
    getBoundingClientRect: () => ({ top: 10000, bottom: 10000, left: 0, right: 0, width: 0, height: 0 }),
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, remove() {},
    insertAdjacentHTML: (position, html) => { const node = { nodeType: 0, textContent: "", html: String(html) }; if (position === "afterbegin") el.children.unshift(node); else el.children.push(node); },
  };
  return el;
};
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"), documentElement: { scrollHeight: 10000, clientHeight: 800 },
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div")); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
// Captured and never fired: this checkpoint covers the first batch only, before any scroll.
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
  observe(target) { this.observed.push(target); } unobserve() {} disconnect() {} };
const requests = [];
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: init?.method ?? "GET", path: url.pathname, query: Object.fromEntries(url.searchParams), body: init?.body ? JSON.parse(init.body) : null });
  const body = url.pathname === "/recommendations" ? process.env.RECOMMENDATIONS_BODY : "{}";
  return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
};
await import(process.env.BUNDLE);
// Every stubbed fetch resolves at once, so the page's loads have settled within a few macrotasks.
for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
process.stdout.write(JSON.stringify({ requests, similar: byId.get("similar-videos")?.innerHTML ?? null, observed: observers.map((o) => o.observed.length) }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_similars")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path) -> dict:
    rows = [{"video_id": f"v{i}", "instance_domain": "videos.example"} for i in range(ROWS)]
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "RECOMMENDATIONS_BODY": json.dumps({"rows": rows, "seed": {"mode": "upnext"}})},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page module ran its loads, so a missing similars request below is the page's, not the runner's
    assert "/api/video" in [r["path"] for r in page["requests"]], page["requests"]
    return page


def test_the_first_batch_is_one_recommendations_request_for_48_rows_of_which_the_first_8_are_shown(bundle):
    page = _page(bundle)

    recommendations = [r for r in page["requests"] if r["path"] == "/recommendations"]
    assert len(recommendations) == 1, recommendations  # C1
    assert recommendations[0]["method"] == "POST" and recommendations[0]["query"].get("limit") == str(ROWS), recommendations  # C1

    markup = page["similar"] or ""
    cards = re.findall(r'<a\b[^>]*\bclass="[^"]*\bsimilar-card-item\b[^"]*"[^>]*>', markup)
    assert len(cards) == SHOWN, (len(cards), markup[:400])  # C2
    shown = [re.search(r'data-video-key="videos\.example::(v\d+)"', card) for card in cards]
    assert [m.group(1) if m else None for m in shown] == [f"v{i}" for i in range(SHOWN)], cards  # C2
