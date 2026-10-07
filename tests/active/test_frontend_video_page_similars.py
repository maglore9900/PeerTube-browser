"""The video page's similars, run in node with the real page module: its first batch is one `/recommendations` request for 48 rows, of which only the first 8 are shown; each sentinel intersection appends the next 8 of the fetched rows, and an intersection once all 48 are shown asks for the next batch, excluding the rows shown.

- The page makes exactly one `/recommendations` request, a POST whose `limit` query parameter is "48" (the limit travels in the query string).
- Answered with 48 distinct rows in up-next mode, `#similar-videos` holds exactly 8 `similar-card-item` cards, and they are the answer's first 8 rows in order.
- One intersection makes exactly one `insertAdjacentHTML("beforeend", …)` call on `#similar-videos`, holding 8 `similar-card-item` cards that are rows 8-15 of the first answer; `innerHTML` is not set again through the five intersections that reveal all 48 rows, and after the first it still begins with the first 8 cards unchanged.
- Five intersections show all 48 rows in order without a second `/recommendations` request; the sixth sends one, a POST whose `exclude` is exactly the first answer's 48 `{id, host}` pairs (`video_id`, `instance_domain`).
- Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel; their count is reported in the first append's failure message.

The runner is the one in `tests/active/test_frontend_video_page.py`, plus an `IntersectionObserver` whose instances are captured, a document taller than the window so filling the viewport never asks for more, and element markup that keeps what `insertAdjacentHTML` adds as well as what `innerHTML` sets. Each element counts its `innerHTML` writes and records its `insertAdjacentHTML` calls, and `getElementById` tags the element with its id. After the page has settled, the runner fires every observer watching `#similar-sentinel` with `[{ isIntersecting: true }]` the case's number of times, settling and snapshotting `#similar-videos` after each. `fetch` records each request's method, path, query and JSON body, answers the case's `/recommendations` POSTs in turn from its list (with no rows once the list runs out), and `{}` elsewhere.
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
INTERSECTIONS = 6

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
    nodeType: 1, tagName: tag.toUpperCase(), hidden, children: [], dataset: {}, style: {}, attrs: {}, parentElement: null, writes: 0, inserts: [],
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? (c.nodeType === 1 ? c.outerHTML : "")).join(""); },
    set innerHTML(v) { el.writes += 1; el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
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
    insertAdjacentHTML: (position, html) => { el.inserts.push({ position, html: String(html) }); const node = { nodeType: 0, textContent: "", html: String(html) }; if (position === "afterbegin") el.children.unshift(node); else el.children.push(node); },
  };
  return el;
};
const byId = new Map();
const getElementById = (id) => { if (!byId.has(id)) { const el = element("div"); el.id = id; byId.set(id, el); } return byId.get(id); };
globalThis.document = {
  title: "", body: element("body"), documentElement: { scrollHeight: 10000, clientHeight: 800 },
  getElementById, createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: (selector) => (/^#[\\w-]+$/.test(selector) ? getElementById(selector.slice(1)) : null), querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
// Captured, then fired by hand below as if the sentinel had scrolled into view.
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
  observe(target) { this.observed.push(target); } unobserve() {} disconnect() {} };
const requests = [];
const answers = JSON.parse(process.env.RECOMMENDATIONS_BODIES);
let answered = 0;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: init?.method ?? "GET", path: url.pathname, query: Object.fromEntries(url.searchParams), body: init?.body ? JSON.parse(init.body) : null });
  const body = url.pathname === "/recommendations" ? JSON.stringify(answers[answered++] ?? { rows: [] }) : "{}";
  return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
};
// Every stubbed fetch resolves at once, so the page's work has settled within a few macrotasks.
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
await import(process.env.BUNDLE);
await settle();
const isSentinel = (target) => target?.id === "similar-sentinel" || target?.attrs?.id === "similar-sentinel";
const watching = observers.filter((o) => o.observed.some(isSentinel));
const grid = getElementById("similar-videos");
const snapshot = () => ({ similar: grid.innerHTML, writes: grid.writes, inserts: grid.inserts.length, recommendations: requests.filter((r) => r.path === "/recommendations").length });
const snapshots = [snapshot()];
for (let i = 0; i < Number(process.env.INTERSECTIONS); i += 1) {
  for (const o of watching) o.callback([{ isIntersecting: true, target: o.observed.find(isSentinel) }], o);
  await settle();
  snapshots.push(snapshot());
}
// A report past 64 KiB is still being flushed to the pipe when write returns, so node exits only once it has drained.
process.stdout.write(JSON.stringify({ requests, sentinelObservers: watching.length, snapshots, inserts: grid.inserts }) + "\\n", () => process.exit(0));
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


def _rows(prefix: str) -> list[dict]:
    return [{"video_id": f"{prefix}{i}", "instance_domain": "videos.example"} for i in range(ROWS)]


def _page(bundle: Path, answers: list[dict], intersections: int = 0) -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "RECOMMENDATIONS_BODIES": json.dumps(answers), "INTERSECTIONS": str(intersections)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page module ran its loads, so a missing similars request below is the page's, not the runner's
    assert "/api/video" in [r["path"] for r in page["requests"]], page["requests"]
    return page


def _keys(markup: str) -> list[str | None]:
    cards = re.findall(r'<div\b[^>]*\bclass="[^"]*\bsimilar-card-item\b[^"]*"[^>]*>', markup)
    return [m.group(1) if (m := re.search(r'data-video-key="videos\.example::(\w+)"', card)) else None for card in cards]


def test_the_first_batch_is_one_recommendations_request_for_48_rows_of_which_the_first_8_are_shown(bundle):
    page = _page(bundle, [{"rows": _rows("v"), "seed": {"mode": "upnext"}}])

    recommendations = [r for r in page["requests"] if r["path"] == "/recommendations"]
    assert len(recommendations) == 1, recommendations
    assert recommendations[0]["method"] == "POST" and recommendations[0]["query"].get("limit") == str(ROWS), recommendations

    markup = page["snapshots"][0]["similar"] or ""
    cards = re.findall(r'<div\b[^>]*\bclass="[^"]*\bsimilar-card-item\b[^"]*"[^>]*>', markup)
    assert len(cards) == SHOWN, (len(cards), markup[:400])
    shown = [re.search(r'data-video-key="videos\.example::(v\d+)"', card) for card in cards]
    assert [m.group(1) if m else None for m in shown] == [f"v{i}" for i in range(SHOWN)], cards


def test_each_sentinel_intersection_appends_the_next_8_rows_and_the_one_after_all_48_asks_for_a_batch_excluding_them(bundle):
    page = _page(bundle, [{"rows": _rows("v"), "seed": {"mode": "upnext"}}, {"rows": _rows("w"), "seed": {"mode": "upnext"}}], INTERSECTIONS)
    loaded, first = page["snapshots"][:2]

    # control: the first batch rendered 8 cards from one request, so the intersections below start from there
    assert _keys(loaded["similar"]) == [f"v{i}" for i in range(SHOWN)] and loaded["recommendations"] == 1, loaded

    # the sentinel observer count is reported with the first append, so a missing append names its cause
    assert first["inserts"] - loaded["inserts"] == 1, {"inserts": (loaded["inserts"], first["inserts"]), "sentinel observers": page["sentinelObservers"]}
    appended = page["inserts"][loaded["inserts"]]
    assert appended["position"] == "beforeend", appended["position"]
    assert _keys(appended["html"]) == [f"v{i}" for i in range(SHOWN, 2 * SHOWN)], appended["html"][:400]
    assert first["writes"] == loaded["writes"], (loaded["writes"], first["writes"])
    assert first["similar"].startswith(loaded["similar"]), first["similar"][:400]

    # each later intersection is checked on its own, so a page that shows the remaining rows in one larger chunk fails at that step
    for k in range(2, (ROWS - SHOWN) // SHOWN + 1):
        step = page["snapshots"][k]
        assert step["inserts"] - page["snapshots"][k - 1]["inserts"] == 1 and _keys(step["similar"]) == [f"v{i}" for i in range(SHOWN * (k + 1))], (k, step["inserts"], _keys(step["similar"]))

    # the 40 rows after the first 8 take five intersections
    revealed = page["snapshots"][(ROWS - SHOWN) // SHOWN]
    assert _keys(revealed["similar"]) == [f"v{i}" for i in range(ROWS)], _keys(revealed["similar"])
    assert revealed["writes"] == loaded["writes"], (loaded["writes"], revealed["writes"])
    assert revealed["recommendations"] == 1, revealed["recommendations"]

    # the sixth intersection finds no unrevealed row
    assert page["snapshots"][INTERSECTIONS]["recommendations"] == 2, page["snapshots"][INTERSECTIONS]["recommendations"]
    second = [r for r in page["requests"] if r["path"] == "/recommendations"][1]
    assert second["method"] == "POST", second
    exclude = (second["body"] or {}).get("exclude") or []
    assert len(exclude) == ROWS and sorted((str(e.get("id")), str(e.get("host"))) for e in exclude) == sorted((f"v{i}", "videos.example") for i in range(ROWS)), exclude
