"""Search result cards carry the card controls on every loaded page, and Like and Dislike on one toggle the reaction and redraw that card in place.

`pages/search/index.ts` is bundled and run in node against a fake DOM that parses the markup it is given, a stub fetch that records each request, and an IntersectionObserver stub that loads page 2 when told the sentinel is in view. Clicks land on the icon inside the button, as a user's would.

- With a key, after page 1 and the appended page 2, every keyed card has the `like`, `dislike`, `channel` and `account` buttons, and the keyless card on each page has none.
- On a page-2 card, Dislike, Dislike, Dislike, Like, Like send `dislike`, `undo_dislike`, `dislike`, `like`, `undo_like` for that video. After each click, the card shows disliked (dislikes stat active, Dislike `aria-pressed="true"`), then neutral, then disliked, then liked and not disliked, then neutral. It stays at its position with its four controls, and no other card changes.
- Without a key, the keyed cards carry the same four controls and the keyless card none; Like sends `like`, `localLikes:v1` then holds the video, and the card shows liked.
- With a key, the first search's cards carry the four controls, and a Like, or in a second run a Dislike, whose response is held while a new search replaces the grid resolves without an error escaping and without writing an error into the clicked card's status line. The grid holds the new search's cards, all unmarked, and a following click of the same reaction on the card of a video both searches returned sends `like` or `dislike`, not the `undo_like` or `undo_dislike` a leftover row from the first search would cause.

The fake DOM throws when outerHTML is set on an element with no parent, as Chromium does. The card's other markup, and the Block buttons' behaviour, are not asserted here.
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
ACTIONS = ["like", "dislike", "channel", "account"]

# The search page runs against a fake DOM that parses the markup it is given, so cards, their buttons and their marks are elements the page can walk with closest/querySelector and replace through outerHTML. Elements fetched by id hang off document.body, which is what isConnected walks to.
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
    // The sentinel sits far below the viewport, so pages load only when the observer reports it in view.
    getBoundingClientRect: () => ({ top: 100000, bottom: 100000, left: 0, right: 0, width: 0, height: 0 }),
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
const holds = [];
let holdNextAction = process.env.HOLD_ACTION === "1";
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: String(init.method ?? "GET").toUpperCase(), path: url.pathname, query: Object.fromEntries(url.searchParams), body: init.body == null ? null : JSON.parse(String(init.body)) });
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/v1/search/videos") {
    const page = pages[url.searchParams.get("q")]?.[Number(url.searchParams.get("page") ?? "1") - 1];
    return new Response(JSON.stringify(page ?? { rows: [], total: 0 }), { status: 200, headers });
  }
  if (url.pathname === "/api/user-action") {
    if (holdNextAction) { holdNextAction = false; await new Promise((resolve) => holds.push(resolve)); }
    return new Response("{}", { status: 200, headers });
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
// A user clicks the icon inside an icon-only button; a disabled button dispatches no click.
const click = (target) => { for (let n = target; n; n = n.parentElement) if (n.tagName === "BUTTON" && n.disabled) return; fire(target, "click"); };
const grid = () => byId.get("search-results");
const cardOf = (key) => grid().children.find((c) => c.dataset.videoKey === key) ?? null;
const cardState = (card) => ({
  key: card.dataset.videoKey ?? null,
  title: card.querySelector(".video-title")?.textContent ?? null,
  actions: card.querySelectorAll("[data-card-action]").map((b) => b.dataset.cardAction),
  likesActive: card.querySelector(".stat.likes")?.classList.contains("active") ?? null,
  likePressed: card.querySelector("[data-card-action=\"like\"]")?.getAttribute("aria-pressed") ?? null,
  dislikesActive: card.querySelector(".stat.dislikes")?.classList.contains("active") ?? null,
  dislikePressed: card.querySelector("[data-card-action=\"dislike\"]")?.getAttribute("aria-pressed") ?? null,
});
const cards = () => grid().children.map(cardState);
const searches = () => requests.filter((r) => r.path === "/api/v1/search/videos").map((r) => [r.query.q, r.query.page ?? "1"]);
const sent = () => requests.filter((r) => r.path === "/api/user-action").map((r) => ({ method: r.method, action: r.body?.action, uuid: r.body?.uuid, host: r.body?.host }));
const press = (key, action) => { const icon = cardOf(key)?.querySelector(`[data-card-action="${action}"] path`); if (icon) click(icon); return Boolean(icon); };
const step = async (key, action) => { const before = sent().length; const pressed = press(key, action); await settle(); const card = cardOf(key); return { action, pressed, sent: sent().slice(before), card: card && cardState(card), grid: cards() }; };

await import(process.env.BUNDLE);
await settle();
const target = process.env.TARGET;
const report = {};
if (process.env.SCENARIO === "paged") {
  for (const callback of observers) callback([{ isIntersecting: true }]);
  await settle();
  report.searches = searches();
  report.grid = cards();
  report.steps = [];
  for (const action of ["dislike", "dislike", "dislike", "like", "like"]) report.steps.push(await step(target, action));
}
if (process.env.SCENARIO === "keyless") {
  report.grid = cards();
  report.storedBefore = localStorage.getItem("localLikes:v1");
  report.like = await step(target, "like");
  report.stored = localStorage.getItem("localLikes:v1");
}
if (process.env.SCENARIO === "reset") {
  const clicked = cardOf(target);
  report.firstGrid = cards();
  report.held = await step(target, process.env.ACTION);
  report.heldOpen = holds.length;
  byId.get("search-input").value = process.env.NEXT_QUERY;
  fire(byId.get("search-form"), "submit");
  await settle();
  report.searches = searches();
  report.beforeRelease = cards();
  for (const release of holds.splice(0)) release();
  await settle();
  report.afterRelease = cards();
  report.clicked = clicked && { connected: clicked.isConnected, status: clicked.querySelector(".card-action-status")?.textContent ?? null };
  report.next = await step(target, process.env.ACTION);
}
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


def _run(bundle: Path, scenario: str, storage: dict, query: str, pages: dict, target: str, next_query: str = "", action: str = "") -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps(storage), "SEARCH": f"?q={query}",
             "PAGES": json.dumps(pages), "SCENARIO": scenario, "TARGET": target, "NEXT_QUERY": next_query, "ACTION": action, "HOLD_ACTION": "1" if scenario == "reset" else "0"},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _row(tag: str) -> dict:
    return {"video_id": tag, "video_uuid": f"uuid-{tag}", "instance_domain": "peer.example", "title": f"video {tag}"}


def _keyless(tag: str) -> dict:
    # No uuid and no id: the row has no video key, so the card has nothing to act on.
    return {"video_id": None, "video_uuid": None, "instance_domain": "peer.example", "title": f"keyless {tag}"}


def _key(row: dict) -> str | None:
    return f"{row['instance_domain']}::{row['video_uuid']}" if row["video_uuid"] else None


def _sent(action: str, row: dict) -> dict:
    return {"method": "POST", "action": action, "uuid": row["video_uuid"], "host": row["instance_domain"]}


def _marks(card: dict) -> tuple:
    return card["likesActive"], card["likePressed"], card["dislikesActive"], card["dislikePressed"]


NEUTRAL = (False, "false", False, "false")
LIKED = (True, "true", False, "false")
DISLIKED = (False, "false", True, "true")
QUERY = "music"
PAGE_1 = [_row("a1"), _keyless("k1"), _row("a2")]
PAGE_2 = [_row("b1"), _row("b2"), _keyless("k2")]
TOTAL = len(PAGE_1) + len(PAGE_2)


def test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place(search_bundle):
    target = PAGE_2[1]
    page = _run(search_bundle, "paged", {PROFILE_KEY: KEY}, QUERY, {QUERY: [{"rows": PAGE_1, "total": TOTAL}, {"rows": PAGE_2, "total": TOTAL}]}, _key(target))

    # control: page 1 loaded on its own and page 2 only when the sentinel came into view, and both pages' cards are in the grid in row order with the keyless rows carrying no key
    assert page["searches"] == [[QUERY, "1"], [QUERY, "2"]], page["searches"]
    assert [(c["key"], c["title"]) for c in page["grid"]] == [(_key(r), r["title"]) for r in PAGE_1 + PAGE_2], page["grid"]
    # A page that renders without actions leaves every list empty; one that passes actions only on the reset path leaves page 2's empty.
    assert {c["key"]: c["actions"] for c in page["grid"] if c["key"]} == {_key(r): ACTIONS for r in PAGE_1 + PAGE_2 if _key(r)}, page["grid"]  # C1
    assert [c["actions"] for c in page["grid"] if not c["key"]] == [[], []], page["grid"]  # C1: keyless cards on both pages stay bare
    assert all(_marks(c) == NEUTRAL for c in page["grid"] if c["key"]), page["grid"]  # control: no card starts marked

    # Dislike, Dislike, Dislike, Like, Like on a page-2 card: each click sends the toggle of the card's current mark and the card is redrawn with the new mark.
    expected = [("dislike", DISLIKED), ("undo_dislike", NEUTRAL), ("dislike", DISLIKED), ("like", LIKED), ("undo_like", NEUTRAL)]
    others = [c for c in page["grid"] if c["key"] != _key(target)]
    for step, (action, marks) in zip(page["steps"], expected, strict=True):
        assert step["pressed"] is True, step  # control: the icon to click exists on the current card
        # A Dislike that always sends dislike, or a Like on a disliked card that sends undo_like, fails here.
        assert step["sent"] == [_sent(action, target)], (step, page["errors"])  # C2
        # A page that sends but does not redraw keeps the previous mark; one that redraws from a stale reaction shows the wrong one.
        assert _marks(step["card"]) == marks, (step["action"], step["card"], page["errors"])  # C2
        assert step["card"]["actions"] == ACTIONS, step["card"]  # C2: the redraw keeps the controls
        # In place: same position in the grid, and no other card changed.
        assert [c["key"] for c in step["grid"]] == [c["key"] for c in page["grid"]], step["grid"]  # C2
        assert [c for c in step["grid"] if c["key"] != _key(target)] == others, step["grid"]  # C2
    assert page["errors"] == [], page["errors"]


def test_a_keyless_like_is_sent_stored_in_the_local_likes_and_shown_on_the_card(search_bundle):
    target = PAGE_1[0]
    page = _run(search_bundle, "keyless", {}, QUERY, {QUERY: [{"rows": PAGE_1, "total": len(PAGE_1)}]}, _key(target))

    assert page["storedBefore"] is None, page  # control: the browser holds no like before the click
    # A page that renders the controls only for a profile holder leaves every list empty here.
    assert [(c["key"], c["actions"]) for c in page["grid"]] == [(_key(r), ACTIONS if _key(r) else []) for r in PAGE_1], page["grid"]  # C1
    assert page["like"]["pressed"] is True, page["grid"]  # control: a keyless visitor's keyed card has a Like button
    # A page that asks for a profile before liking sends nothing.
    assert page["like"]["sent"] == [_sent("like", target)], (page["like"], page["errors"])  # C2
    assert json.loads(page["stored"] or "null") == [{"video_uuid": target["video_uuid"], "instance_domain": target["instance_domain"]}], page["stored"]  # C2
    assert _marks(page["like"]["card"]) == LIKED, page["like"]["card"]  # C2: redrawn from the local likes
    assert page["errors"] == [], page["errors"]


@pytest.mark.parametrize(("action", "mark"), [("like", LIKED), ("dislike", DISLIKED)])
def test_a_like_or_dislike_resolving_after_a_new_search_replaced_the_grid_leaves_the_new_cards_and_rows_alone(search_bundle, action, mark):
    first = [_row("a1"), _row("a2"), _row("a3")]
    second = [_row("c1"), _row("a2"), _row("c2")]  # a2 is in both searches
    shared = first[1]
    page = _run(search_bundle, "reset", {PROFILE_KEY: KEY}, "first",
                {"first": [{"rows": first, "total": len(first)}], "second": [{"rows": second, "total": len(second)}]}, _key(shared), next_query="second", action=action)

    assert [(c["key"], c["actions"]) for c in page["firstGrid"]] == [(_key(r), ACTIONS) for r in first], page["firstGrid"]  # C1: the cards a fresh search renders carry the controls
    # control: the reaction left, and its response is held while the second search loads and replaces the grid
    assert page["held"]["sent"] == [_sent(action, shared)] and page["heldOpen"] == 1, (page["held"], page["errors"])
    assert page["searches"] == [["first", "1"], ["second", "1"]], page["searches"]
    assert [c["key"] for c in page["beforeRelease"]] == [_key(r) for r in second], page["beforeRelease"]
    assert page["clicked"]["connected"] is False, page["clicked"]  # control: the clicked card is detached when the reaction resolves

    # Redrawing the detached card throws; a page that does not check for that, on either the Like or the Dislike branch, reports the error on the clicked card or lets it escape.
    assert page["errors"] == [], page["errors"]  # C2
    assert page["clicked"]["status"] == "", page["clicked"]  # C2
    # The resolved reaction does not reach the new grid: it holds the second search's cards, a2 unmarked as that search returned it.
    assert [c["key"] for c in page["afterRelease"]] == [_key(r) for r in second], page["afterRelease"]  # C2
    assert all(_marks(c) == NEUTRAL for c in page["afterRelease"]), page["afterRelease"]  # C2
    # A row list the reset did not clear still holds the first search's a2, now marked, which the lookup finds first and so sends the undo.
    assert page["next"]["sent"] == [_sent(action, shared)], (page["next"], page["errors"])  # C2
    assert _marks(page["next"]["card"]) == mark, page["next"]["card"]  # C2
