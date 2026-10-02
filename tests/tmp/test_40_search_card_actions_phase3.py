"""Block channel and Block account on a search card block the source and dislike the video, then take every loaded card of that source off the grid and refill it; a block whose dislike fails says so on the card and removes nothing.

`pages/search/index.ts` is bundled and run in node against a fake DOM that parses the markup it is given, a stub fetch that records each request, and an IntersectionObserver stub that loads page 2 when told the sentinel is in view. The sentinel reports itself in view only from the click on, so a page fetched after the click was asked for by the page itself; nothing here shows whether that fetch came before or after the cards were removed.

- With a key, Block channel on a page-1 card sends `POST /api/profile/blocks` for that video, then a `dislike` for it, then fetches page 3. The cards left are exactly the loaded ones not on that `instance_domain`+`channel_id`, in order: page-2 cards and a keyless card of the channel go, a card on the same `channel_id` of another instance and a card of the same account on another channel stay. Block account does the same on `account_url`, so that same-account card goes too. Page 3 comes back empty, so `#search-status` reads as it did before the click.
- When the `dislike` after the block answers 500, the clicked card's `.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`, with the action name in place of an empty label, and every card is still in the grid, in order.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
ENTRY = FRONTEND / "src" / "pages" / "search" / "index.ts"
BASE = "http://client.test"
PROFILE_KEY = "profileKey:v1"
KEY = "K" * 43

# The phase-2 fake DOM, with a sentinel that can be put in view and stub routes for the block and a failing dislike.
RUNNER = r"""
const memory = (seed) => { const s = new Map(Object.entries(seed)); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory(JSON.parse(process.env.STORAGE));
globalThis.sessionStorage = memory({});
globalThis.window = { location: { origin: process.env.BASE, pathname: "/search.html", search: process.env.SEARCH }, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage,
  innerHeight: 800, scrollY: 0, history: { pushState() {}, replaceState() {} }, addEventListener() {} };

const VOID = new Set(["area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: "\"", "#39": "'" };
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (_m, e) => ENTITIES[e]);
const escapeText = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c]);
const TOKEN = /<\/([\w-]+)\s*>|<([\w-]+)((?:\s+[^\s=/>]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g;
const ATTR = /([^\s=/>]+)(?:="([^"]*)")?/g;
const kebab = (k) => k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
const detach = (n) => { const p = n.parentElement; if (p) p.childNodes.splice(p.childNodes.indexOf(n), 1); n.parentElement = null; };
const text = (v) => ({ nodeType: 3, data: String(v), parentElement: null, get textContent() { return this.data; } });
const serialize = (n) => {
  if (n.nodeType === 3) return escapeText(n.data);
  const tag = n.tagName.toLowerCase();
  const attrs = Object.entries(n.attrs).map(([k, v]) => ` ${k}="${escapeText(v)}"`).join("");
  return VOID.has(tag) ? `<${tag}${attrs}>` : `<${tag}${attrs}>${n.childNodes.map(serialize).join("")}</${tag}>`;
};
const parse = (html) => {
  const root = element("template");
  const open = [root];
  for (const [, close, tag, attrs, selfClose, txt] of String(html).matchAll(TOKEN)) {
    const top = open[open.length - 1];
    if (txt !== undefined) top.append(text(decode(txt)));
    else if (close) { const i = open.findLastIndex((n) => n.tagName === close.toUpperCase()); if (i > 0) open.length = i; }
    else {
      const el = element(tag);
      for (const [, name, value] of attrs.matchAll(ATTR)) el.setAttribute(name, decode(value ?? ""));
      top.append(el);
      if (!selfClose && !VOID.has(tag.toLowerCase())) open.push(el);
    }
  }
  const nodes = [...root.childNodes];
  nodes.forEach(detach);
  return nodes;
};
// Simple and compound selectors, joined by descendant combinators or commas; anything else throws so an unsupported query fails loudly instead of matching nothing.
const COMPOUND = /^([\w-]+|\*)?((?:\.[\w-]+|\[[\w-]+(?:="[^"]*")?\])*)$/;
const matchesCompound = (el, compound) => {
  const m = COMPOUND.exec(compound);
  if (!m || !compound) throw new Error(`fake DOM: unsupported selector ${compound}`);
  if (m[1] && m[1] !== "*" && el.tagName !== m[1].toUpperCase()) return false;
  for (const [, cls, attr, value] of m[2].matchAll(/\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g)) {
    if (cls && !el.classList.contains(cls)) return false;
    if (attr && (!(attr in el.attrs) || (value !== undefined && el.attrs[attr] !== value))) return false;
  }
  return true;
};
const matches = (el, selector) => selector.split(",").some((part) => {
  const steps = part.trim().split(/\s+/);
  if (!matchesCompound(el, steps[steps.length - 1])) return false;
  let node = el.parentElement;
  for (let i = steps.length - 2; i >= 0; i -= 1) {
    while (node && !matchesCompound(node, steps[i])) node = node.parentElement;
    if (!node) return false;
    node = node.parentElement;
  }
  return true;
});
const descend = (n) => n.children.flatMap((c) => [c, ...descend(c)]);
// Off screen until the runner says otherwise; only the sentinel can come into view.
let sentinelInView = false;
const element = (tag) => {
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), attrs: {}, childNodes: [], parentElement: null, listeners: {}, disabled: false, value: "", style: {},
    get children() { return el.childNodes.filter((n) => n.nodeType === 1); },
    get className() { return el.attrs.class ?? ""; }, set className(v) { el.attrs.class = String(v); },
    get textContent() { return el.childNodes.map((n) => n.textContent).join(""); },
    set textContent(v) { el.replaceChildren(...(v == null || v === "" ? [] : [text(v)])); },
    get innerHTML() { return el.childNodes.map(serialize).join(""); },
    set innerHTML(v) { el.replaceChildren(...parse(v)); },
    get outerHTML() { return serialize(el); },
    // Chromium throws here for an element with no parent (NoModificationAllowedError), which is the case a detached card meets.
    set outerHTML(v) {
      const parent = el.parentElement;
      if (!parent) throw new Error("NoModificationAllowedError: This element has no parent node.");
      const nodes = parse(v);
      parent.childNodes.splice(parent.childNodes.indexOf(el), 1, ...nodes);
      for (const n of nodes) n.parentElement = parent;
      el.parentElement = null;
    },
    get isConnected() { let n = el; while (n.parentElement) n = n.parentElement; return n === document.body; },
    dataset: new Proxy({}, { get: (_t, k) => el.attrs[`data-${kebab(String(k))}`], set: (_t, k, v) => { el.attrs[`data-${kebab(String(k))}`] = String(v); return true; } }),
    classList: {
      contains: (c) => el.className.split(/\s+/).includes(c),
      add: (...cs) => { el.className = [...new Set([...el.className.split(/\s+/).filter(Boolean), ...cs])].join(" "); },
      remove: (...cs) => { el.className = el.className.split(/\s+/).filter((c) => c && !cs.includes(c)).join(" "); },
      toggle: (c, force) => { const on = force ?? !el.classList.contains(c); if (on) el.classList.add(c); else el.classList.remove(c); return on; },
    },
    append: (...items) => { for (const item of items) { const node = typeof item === "string" ? text(item) : item; detach(node); node.parentElement = el; el.childNodes.push(node); } },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { for (const n of el.childNodes) n.parentElement = null; el.childNodes = []; el.append(...items); },
    remove: () => detach(el),
    insertAdjacentHTML: (position, html) => {
      const nodes = parse(html);
      if (position === "beforeend") el.append(...nodes);
      else if (position === "afterbegin") { el.childNodes.unshift(...nodes); for (const n of nodes) n.parentElement = el; }
      else throw new Error(`fake DOM: unsupported insertAdjacentHTML position ${position}`);
    },
    setAttribute: (n, v) => { el.attrs[n] = String(v); if (n === "disabled") el.disabled = true; },
    getAttribute: (n) => el.attrs[n] ?? null, hasAttribute: (n) => n in el.attrs,
    removeAttribute: (n) => { delete el.attrs[n]; if (n === "disabled") el.disabled = false; },
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); },
    removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    matches: (s) => matches(el, s),
    closest: (s) => { for (let n = el; n; n = n.parentElement) if (matches(n, s)) return n; return null; },
    querySelector: (s) => descend(el).find((n) => matches(n, s)) ?? null,
    querySelectorAll: (s) => descend(el).filter((n) => matches(n, s)),
    getBoundingClientRect: () => { const top = sentinelInView && el.attrs.id === "search-sentinel" ? 0 : 100000; return { top, bottom: top, left: 0, right: 0, width: 0, height: 0 }; },
    focus() {}, select() {},
  };
  return el;
};
const byId = new Map();
globalThis.document = { title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) { const el = element("div"); el.attrs.id = id; document.body.append(el); byId.set(id, el); } return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (v) => text(v), querySelector: (s) => document.body.querySelector(s), querySelectorAll: (s) => document.body.querySelectorAll(s), addEventListener() {} };
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { observers.push(callback); } observe() {} unobserve() {} disconnect() {} };

const pages = JSON.parse(process.env.PAGES);
const requests = [];
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: String(init.method ?? "GET").toUpperCase(), path: url.pathname, query: Object.fromEntries(url.searchParams), body: init.body == null ? null : JSON.parse(String(init.body)) });
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/v1/search/videos") {
    const page = pages[url.searchParams.get("q")]?.[Number(url.searchParams.get("page") ?? "1") - 1];
    return new Response(JSON.stringify(page ?? { rows: [], total: 0 }), { status: 200, headers });
  }
  if (url.pathname === "/api/profile/blocks" && init.method === "POST") {
    return new Response(JSON.stringify({ block: JSON.parse(process.env.BLOCK) }), { status: 200, headers });
  }
  if (url.pathname === "/api/user-action") {
    const status = Number(process.env.DISLIKE_STATUS);
    return new Response(JSON.stringify(status === 200 ? {} : { error: process.env.DISLIKE_ERROR }), { status, headers });
  }
  return new Response(JSON.stringify({ error: "unexpected route" }), { status: 404, headers });
};
const errors = [];
process.on("unhandledRejection", (r) => { errors.push(String(r && r.stack || r)); });
process.on("uncaughtException", (e) => { errors.push(String(e && e.stack || e)); });
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 10)); };
// Events bubble through parentElement; a listener that throws is recorded, as a browser would report it.
const fire = (target, type) => {
  const event = { type, target, bubbles: true, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() { event.stopped = true; } };
  for (let node = target; node && !event.stopped; node = node.parentElement) {
    event.currentTarget = node;
    for (const l of [...(node.listeners[type] ?? [])]) { try { l.call(node, event); } catch (e) { errors.push(String(e && e.stack || e)); } }
  }
};
const grid = () => byId.get("search-results");
const cardOf = (key) => grid().children.find((c) => c.dataset.videoKey === key) ?? null;
const cards = () => grid().children.map((card) => card.querySelector(".video-title")?.textContent ?? null);
const status = () => byId.get("search-status").textContent;
const calls = (from) => requests.slice(from).map((r) => r.path === "/api/v1/search/videos" ? [r.method, r.path, r.query.q, r.query.page ?? "1"]
  : r.path === "/api/user-action" ? [r.method, r.path, { action: r.body?.action, uuid: r.body?.uuid, host: r.body?.host }] : [r.method, r.path, r.body]);

await import(process.env.BUNDLE);
await settle();
for (const callback of observers) callback([{ isIntersecting: true }]);
await settle();
const report = { before: { calls: calls(0), grid: cards(), status: status() } };
const sentBefore = requests.length;
sentinelInView = true;
const button = cardOf(process.env.TARGET)?.querySelector(`[data-card-action="${process.env.ACTION}"]`);
report.pressed = Boolean(button);
if (button) fire(button, "click");
await settle();
const clicked = cardOf(process.env.TARGET);
report.after = { calls: calls(sentBefore), grid: cards(), status: status(), cardStatus: clicked?.querySelector(".card-action-status")?.textContent ?? null };
report.errors = errors;
process.stdout.write(JSON.stringify(report) + "\n", () => process.exit(0));
"""


def _bundle(entry: Path, out: Path) -> Path:
    run = subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    (out / "runner.mjs").write_text(RUNNER)
    return out


@pytest.fixture(scope="module")
def search_bundle(tmp_path_factory) -> Path:
    return _bundle(ENTRY, tmp_path_factory.mktemp("search"))


def _run(bundle: Path, action: str, block: dict, dislike_status: int, dislike_error: str = "") -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps({PROFILE_KEY: KEY}), "SEARCH": f"?q={QUERY}",
             "PAGES": json.dumps(PAGES), "TARGET": _key(TARGET), "ACTION": action, "BLOCK": json.dumps(block), "DISLIKE_STATUS": str(dislike_status), "DISLIKE_ERROR": dislike_error},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _row(tag: str, domain: str, channel: str, account: str, keyed: bool = True) -> dict:
    # A keyless row has no uuid and no id, so its card has no video key and no controls of its own.
    return {"video_id": tag if keyed else None, "video_uuid": f"uuid-{tag}" if keyed else None, "instance_domain": domain, "channel_id": channel, "account_url": account, "title": f"video {tag}"}


def _key(row: dict) -> str:
    return f"{row['instance_domain']}::{row['video_uuid']}"


ALICE = "https://peer.example/accounts/alice"
QUERY = "music"
TARGET = _row("a1", "peer.example", "7", ALICE)
PAGE_1 = [
    TARGET,
    _row("a2", "peer.example", "8", ALICE),  # same account, another channel
    _row("k1", "peer.example", "9", "https://peer.example/accounts/carol", keyed=False),
    _row("a3", "other.example", "7", "https://other.example/accounts/dave"),  # same channel_id on another instance
]
PAGE_2 = [
    _row("b1", "peer.example", "7", ALICE),  # same channel and account, on page 2
    _row("b2", "peer.example", "10", "https://peer.example/accounts/erin"),
    _row("k2", "peer.example", "7", ALICE, keyed=False),  # same channel and account, keyless
]
TOTAL = 9  # more than the 7 loaded, so a third page exists; it comes back empty, which leaves the status line's counts as they were
PAGES = {QUERY: [{"rows": PAGE_1, "total": TOTAL}, {"rows": PAGE_2, "total": TOTAL}, {"rows": [], "total": TOTAL}]}
ALL_TITLES = ["video a1", "video a2", "video k1", "video a3", "video b1", "video b2", "video k2"]
STATUS = "Showing 7 of 9 matched videos."
BLOCK = {"kind": "channel", "instance_domain": "peer.example", "channel_id": "7", "account_url": ALICE, "label": "Alice's channel"}
DISLIKE_ERROR = "reaction store unavailable"


def _block(kind: str, label: str) -> dict:
    return {**BLOCK, "kind": kind, "label": label}


def _block_then_dislike(kind: str) -> list:
    return [["POST", "/api/profile/blocks", {"kind": kind, "uuid": TARGET["video_uuid"], "host": TARGET["instance_domain"]}],
            ["POST", "/api/user-action", {"action": "dislike", "uuid": TARGET["video_uuid"], "host": TARGET["instance_domain"]}]]


def _control_before(page: dict) -> None:
    # control: page 1 loaded, page 2 only when the observer reported the sentinel, page 3 not yet, and every row is a card
    assert page["before"]["calls"] == [["GET", "/api/v1/search/videos", QUERY, "1"], ["GET", "/api/v1/search/videos", QUERY, "2"]], page["before"]
    assert page["before"]["grid"] == ALL_TITLES, page["before"]
    assert page["before"]["status"] == STATUS, page["before"]
    assert page["pressed"] is True, page["before"]  # control: the clicked card carries the button


@pytest.mark.parametrize(("kind", "left"), [
    # a2 shares the account but not the channel; a3 shares the channel_id but not the instance.
    ("channel", ["video a2", "video k1", "video a3", "video b2"]),
    ("account", ["video k1", "video a3", "video b2"]),
])
def test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid(search_bundle, kind, left):
    page = _run(search_bundle, kind, _block(kind, "Alice"), 200)
    _control_before(page)

    # A page with no Block branch sends nothing; one that skips or reorders the dislike, or never refills, fails on the sequence.
    assert page["after"]["calls"] == _block_then_dislike(kind) + [["GET", "/api/v1/search/videos", QUERY, "3"]], (page["after"], page["errors"])  # C1
    # A page that removes only the clicked card keeps b1 and k2; one that matches on channel_id alone drops a3; one that matches the wrong field keeps or drops a2.
    assert page["after"]["grid"] == left, page["after"]  # C1
    # A page that recounts the status from the cards left, or writes the block into it, changes it.
    assert page["after"]["status"] == STATUS, page["after"]  # C1
    assert page["errors"] == [], page["errors"]  # C1


@pytest.mark.parametrize(("kind", "label", "shown"), [("channel", "Alice's channel", "Alice's channel"), ("account", "", "account")])
def test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing(search_bundle, kind, label, shown):
    page = _run(search_bundle, kind, _block(kind, label), 500, DISLIKE_ERROR)
    _control_before(page)

    # A page that reports only the dislike error, or reports nothing, fails here; an empty label falls back to the action.
    assert page["after"]["cardStatus"] == f"Blocked {shown}, but the dislike failed: {DISLIKE_ERROR}", (page["after"], page["errors"])  # C2
    # Arms the grid check below: the block was sent and the dislike that followed it was the request that failed, so the removal path was reached and declined.
    assert page["after"]["calls"][:2] == _block_then_dislike(kind), (page["after"], page["errors"])
    # A page that removes the source's cards whatever the dislike returned leaves fewer.
    assert page["after"]["grid"] == ALL_TITLES, page["after"]  # C2
    assert page["errors"] == [], page["errors"]  # C2
