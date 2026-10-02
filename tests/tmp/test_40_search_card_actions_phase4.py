"""A search-card Dislike or Block without a profile key asks for a profile on the card and sends nothing; a card action the Client rejects shows its error, gives the button back and leaves the card's reaction as it was.

`pages/search/index.ts` is bundled and run in node against the phase-2 fake DOM, with a stub fetch that records every request. Clicks land on the icon inside an icon button, or on a text button itself.

- Without a key, Dislike, Block channel and Block account each leave the stub fetch with no new request and put home's exact "Disliking needs a profile. Create one from the Profile button." or "Blocking needs a profile. Create one from the Profile button." in the clicked card's `.card-action-status`. A keyless Like in the same run is sent, so the stub does record requests.
- With a key, each of Like, Dislike, Block channel and Block account, on a neutral card and in a second run on a liked one, is rejected with the Client backend's own error: 404 `Video not found in Engine` for Like, 400 `Dislike limit reached (1000)` for Dislike, 400 `Block limit reached (1000)` for a Block. The button is disabled while the response is held. Once it lands, that message is in the card's status line, the clicked button's `disabled` is false, the card is still on the grid showing the mark it had before, and a Dislike then a Like on it send `dislike` then `like` from a neutral card, `dislike` then `undo_like` from a liked one, so the row's reaction is as it was.
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

# The phase-2 fake DOM, with a stub fetch that answers every reaction and block with ACTION_STATUS and can hold the first one open.
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
  if (url.pathname === "/api/user-action" || url.pathname === "/api/profile/blocks") {
    if (holdNextAction) { holdNextAction = false; await new Promise((resolve) => holds.push(resolve)); }
    const status = Number(process.env.ACTION_STATUS);
    return new Response(JSON.stringify(status === 200 ? {} : { error: process.env.ACTION_ERROR }), { status, headers });
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
// A user clicks the icon inside an icon-only button, or the label of a text button; a disabled button dispatches no click.
const click = (target) => { for (let n = target; n; n = n.parentElement) if (n.tagName === "BUTTON" && n.disabled) return; fire(target, "click"); };
const grid = () => byId.get("search-results");
const cardOf = (key) => grid().children.find((c) => c.dataset.videoKey === key) ?? null;
const buttonOf = (key, action) => cardOf(key)?.querySelector(`[data-card-action="${action}"]`) ?? null;
const cardState = (card) => card && ({
  key: card.dataset.videoKey ?? null,
  actions: card.querySelectorAll("[data-card-action]").map((b) => b.dataset.cardAction),
  likesActive: card.querySelector(".stat.likes")?.classList.contains("active") ?? null,
  likePressed: card.querySelector("[data-card-action=\"like\"]")?.getAttribute("aria-pressed") ?? null,
  dislikesActive: card.querySelector(".stat.dislikes")?.classList.contains("active") ?? null,
  dislikePressed: card.querySelector("[data-card-action=\"dislike\"]")?.getAttribute("aria-pressed") ?? null,
  status: card.querySelector(".card-action-status")?.textContent ?? null,
});
const calls = (from) => requests.slice(from).map((r) => r.path === "/api/user-action" ? [r.method, r.path, { action: r.body?.action, uuid: r.body?.uuid, host: r.body?.host }] : [r.method, r.path, r.body]);
const press = (key, action) => { const button = buttonOf(key, action); if (button) click(button.querySelector("path") ?? button); return button; };
const step = async (key, action) => { const before = requests.length; const button = press(key, action); await settle(); return { action, pressed: Boolean(button), sent: calls(before), card: cardState(cardOf(key)) }; };

await import(process.env.BUNDLE);
await settle();
const target = process.env.TARGET;
const report = { searches: calls(0), card: cardState(cardOf(target)) };
if (process.env.SCENARIO === "keyless") {
  report.prompt = await step(target, process.env.ACTION);
  report.like = await step(target, "like");
}
if (process.env.SCENARIO === "rejected") {
  const before = requests.length;
  const button = press(target, process.env.ACTION);
  await settle();
  report.held = { pressed: Boolean(button), open: holds.length, disabled: button?.disabled ?? null, sent: calls(before) };
  for (const release of holds.splice(0)) release();
  await settle();
  report.rejected = { disabled: button?.disabled ?? null, connected: button?.isConnected ?? null, sent: calls(before), card: cardState(cardOf(target)) };
  report.again = [await step(target, "dislike"), await step(target, "like")];
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


def _run(bundle: Path, scenario: str, storage: dict, rows: list, target: dict, action: str = "", status: int = 200, error: str = "") -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps(storage), "SEARCH": f"?q={QUERY}",
             "PAGES": json.dumps({QUERY: [{"rows": rows, "total": len(rows)}]}), "SCENARIO": scenario, "TARGET": _key(target), "ACTION": action,
             "ACTION_STATUS": str(status), "ACTION_ERROR": error, "HOLD_ACTION": "1" if scenario == "rejected" else "0"},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _row(tag: str, reaction: str | None = None) -> dict:
    return {"video_id": tag, "video_uuid": f"uuid-{tag}", "instance_domain": "peer.example", "channel_id": "7", "account_url": "https://peer.example/accounts/alice", "title": f"video {tag}", "reaction": reaction}


def _key(row: dict) -> str:
    return f"{row['instance_domain']}::{row['video_uuid']}"


def _sent(action: str, row: dict) -> list:
    return ["POST", "/api/user-action", {"action": action, "uuid": row["video_uuid"], "host": row["instance_domain"]}]


def _blocked(kind: str, row: dict) -> list:
    return ["POST", "/api/profile/blocks", {"kind": kind, "uuid": row["video_uuid"], "host": row["instance_domain"]}]


def _marks(card: dict) -> tuple:
    return card["likesActive"], card["likePressed"], card["dislikesActive"], card["dislikePressed"]


NEUTRAL = (False, "false", False, "false")
LIKED = (True, "true", False, "false")
QUERY = "music"
SEARCH_PAGE_1 = [["GET", "/api/v1/search/videos", None]]
LIMIT_ERROR = "Dislike limit reached (1000)"  # the Client backend's 400 body for the dislike cap
BLOCK_LIMIT_ERROR = "Block limit reached (1000)"  # the Client backend's 400 body for the block cap
NOT_FOUND_ERROR = "Video not found in Engine"  # the Client backend's 404 body for a reaction to a video the Engine does not hold


@pytest.mark.parametrize(("action", "prompt"), [
    ("dislike", "Disliking needs a profile. Create one from the Profile button."),
    ("channel", "Blocking needs a profile. Create one from the Profile button."),
    ("account", "Blocking needs a profile. Create one from the Profile button."),
])
def test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing(search_bundle, action, prompt):
    target = _row("a1")
    rows = [target, _row("a2")]
    page = _run(search_bundle, "keyless", {}, rows, target, action=action)

    # control: no key, so only page 1 was fetched and the target card carries the four controls, unmarked
    assert page["searches"] == SEARCH_PAGE_1, page["searches"]
    assert page["card"]["actions"] == ACTIONS and _marks(page["card"]) == NEUTRAL, page["card"]
    assert page["prompt"]["pressed"] is True, page["card"]

    # A page with no key guard sends the dislike or the block; one that guards only Dislike sends the block.
    assert page["prompt"]["sent"] == [], (page["prompt"], page["errors"])  # C1
    # A page that sends and shows the server's error, or a prompt worded differently from home's, fails here.
    assert page["prompt"]["card"]["status"] == prompt, (page["prompt"], page["errors"])  # C1
    # control: in the same run, a keyless Like is sent and recorded, so the empty list above is not a fetch stub that records nothing
    assert page["like"]["sent"] == [_sent("like", target)], (page["like"], page["errors"])
    assert page["errors"] == [], page["errors"]


@pytest.mark.parametrize(("action", "status", "error"), [
    ("like", 404, NOT_FOUND_ERROR),
    ("dislike", 400, LIMIT_ERROR),
    ("channel", 400, BLOCK_LIMIT_ERROR),
    ("account", 400, BLOCK_LIMIT_ERROR),
])
@pytest.mark.parametrize(("reaction", "mark", "like"), [(None, NEUTRAL, "like"), ("liked", LIKED, "undo_like")])
def test_a_rejected_card_action_shows_the_error_re_enables_the_button_and_keeps_the_reaction(search_bundle, action, status, error, reaction, mark, like):
    target = _row("a1", reaction)
    rows = [_row("a0"), target, _row("a2")]
    page = _run(search_bundle, "rejected", {PROFILE_KEY: KEY}, rows, target, action=action, status=status, error=error)
    request = _blocked(action, target) if action in ("channel", "account") else _sent(like if action == "like" else "dislike", target)

    # control: page 1 was fetched and the target card shows the mark the search returned
    assert page["searches"] == SEARCH_PAGE_1, page["searches"]
    assert page["card"]["actions"] == ACTIONS and _marks(page["card"]) == mark, page["card"]
    # control: the action's request left and, while its response is held, the button is disabled, so "enabled" below is the button coming back
    assert page["held"]["pressed"] is True and page["held"]["open"] == 1, page["held"]
    assert page["held"]["sent"] == [request], (page["held"], page["errors"])
    assert page["held"]["disabled"] is True, page["held"]

    # A page that takes the blocked source's cards off the grid before the block is accepted has no card here.
    assert page["rejected"]["card"] is not None, (page["rejected"], page["errors"])  # C2
    # A page that shows a generic failure, or nothing, fails here.
    assert page["rejected"]["card"]["status"] == error, (page["rejected"], page["errors"])  # C2
    # A page that re-enables only on success leaves the clicked button disabled.
    assert page["rejected"]["disabled"] is False, page["rejected"]  # C2
    # A page that redraws or marks the card before the request and does not take it back shows a different mark here.
    assert _marks(page["rejected"]["card"]) == mark, page["rejected"]["card"]  # C2
    # The row's reaction is unchanged: a row left disliked sends undo_dislike, a liked row cleared to null sends like, a neutral row left liked sends undo_like.
    assert [step["pressed"] for step in page["again"]] == [True, True], page["again"]  # control: the card still has its Dislike and Like buttons
    assert [step["sent"] for step in page["again"]] == [[_sent("dislike", target)], [_sent(like, target)]], (page["again"], page["errors"])  # C2
    assert page["errors"] == [], page["errors"]  # C2
