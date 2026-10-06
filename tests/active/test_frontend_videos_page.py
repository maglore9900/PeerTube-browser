"""The home page's Profile modal holds a "Hide NSFW videos" checkbox, in each profile state, that reloads the home feed under its new value and leaves the page fetched under that value shown.

`pages/videos/index.ts` is bundled and run in node against recording elements and a stub fetch. It runs for a keyless visitor, a visitor holding a key, and one who has just clicked "Create profile" (the issued-key view).

- The first feed request is to /recommendations with mode recommendations and no nsfw, and its response is held.
- The Profile modal holds exactly one checkbox, and it is checked.
- Unchecking the box (click, input, change) sends exactly one more feed request, with mode recommendations and nsfw=1, which is answered at once. The held first page is then released and read by the page, and the feed shows the second page's rows.
- Checking it again sends one more feed request, with no nsfw, and the feed shows that third page's rows.

The feed is read as the `data-video-key`s in `#video-cards`. The checkbox's label text, its place in the modal and its styling are not asserted.

The card follow controls and the Following feed, with the module bundled and run in node on a recording DOM that parses innerHTML (`DOM_JS` + `PAGE_RUNNER`), so delegated clicks, `closest` and `querySelector` work and a redraw replaces element objects; `fetch` is stubbed per case and the feed is answered only after the follow list:
- Keyed, with a list of one channel on peer.example and one account. Both cards of that channel read "Unfollow channel", the card of that account reads "Unfollow account", and a card with the same channel_id on another host reads "Follow channel" / "Follow account". Unfollowing card 1's channel posts its key to `/api/profile/follows/remove` and relabels both cards of the channel. Following card 2's account posts `{kind, uuid, host}` to `/api/profile/follows` and relabels both cards of that account, but not the other host's card. A follow the Client refuses with a 400 leaves every label as it was and shows the error in that card's status. No card element is replaced over the toggles, and the list is fetched once.
- Keyless: every card reads "Follow channel" / "Follow account". A click on either shows "Following needs a profile. Create one from the Profile button." in that card's status and leaves the labels, and nothing is sent to `/api/profile/follows*`.
- Keyless, with `?mode=following`: no feed request and no cards, and that message is shown.
- Keyed, with `?mode=following`, the first feed request carries no cursor and gets an empty page with cursor `c1`. The page asks again with `c1`, gets two rows and no cursor, shows those two cards, and asks no more.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
PROFILE_KEY = "profileKey:v1"

# The home page module runs against recording elements created on first lookup. The first feed request's response is held until the toggle's own response has been answered and settled, then released, so a load that renders whatever resolves last shows the first page.
HOME_RUNNER = """
const memory = (seed) => { const s = new Map(Object.entries(seed)); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory(JSON.parse(process.env.STORAGE));
globalThis.sessionStorage = memory({});
globalThis.window = { location: { origin: process.env.BASE, pathname: "/", search: "" }, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage,
  innerHeight: 800, scrollY: 0, addEventListener() {}, confirm: () => true };
const text = (v) => ({ nodeType: 3, textContent: String(v), parentElement: null });
const element = (tag) => {
  const el = { nodeType: 1, tagName: tag.toUpperCase(), hidden: false, disabled: false, checked: false, value: "", children: [], dataset: {}, style: {}, attrs: {}, listeners: {}, parentElement: null, html: null, className: "",
    get textContent() { return el.html ?? el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.html = null; el.children = v == null || v === "" ? [] : [text(v)]; },
    get innerHTML() { return el.html ?? ""; },
    set innerHTML(v) { el.children = []; el.html = String(v); },
    get type() { return el.attrs.type ?? ""; }, set type(v) { el.attrs.type = String(v); },
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    append: (...items) => { for (const item of items) { const node = typeof item === "string" ? text(item) : item; node.parentElement = el; el.children.push(node); } },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { el.html = null; el.children = []; el.append(...items); },
    setAttribute: (n, v) => { if (n === "hidden") el.hidden = true; else if (n === "checked") el.checked = true; else el.attrs[n] = String(v); },
    removeAttribute: (n) => { if (n === "hidden") el.hidden = false; else if (n === "checked") el.checked = false; else delete el.attrs[n]; },
    hasAttribute: (n) => (n === "hidden" ? el.hidden : n in el.attrs), getAttribute: (n) => el.attrs[n] ?? null,
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); }, removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    insertAdjacentHTML: (p, h) => { el.html = (el.html ?? "") + String(h); },
    closest: () => null, querySelector: () => null, querySelectorAll: () => [], focus() {}, select() {}, remove() {},
  };
  return el;
};
const byId = new Map();
// A tall document keeps the page from filling the viewport with more batches, so the only feed requests are the loads.
globalThis.document = { title: "", body: element("body"), documentElement: { scrollHeight: 100000 },
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div")); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (v) => text(v), querySelector: () => null, querySelectorAll: () => [], addEventListener() {} };
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
const pages = JSON.parse(process.env.PAGES);
const feed = [];
let release = null;
let firstBodyRead = false;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/profile") return new Response(JSON.stringify({ key: process.env.ISSUED_KEY, profile_id: "p1" }), { status: 201, headers });
  if (url.pathname !== "/recommendations") return new Response("{}", { status: 404, headers });
  const i = feed.length;
  feed.push({ mode: url.searchParams.getAll("mode"), nsfw: url.searchParams.getAll("nsfw") });
  const response = new Response(JSON.stringify({ rows: pages[i] ?? [] }), { status: 200, headers });
  if (i !== 0) return response;
  await new Promise((resolve) => { release = resolve; });
  const json = response.json.bind(response);
  response.json = async () => { firstBodyRead = true; return json(); };
  return response;
};
const rejections = [];
process.on("unhandledRejection", (r) => { rejections.push(String(r && r.stack || r)); });
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 10)); };
// Events bubble through parentElement, so a listener on the input, its label or the section all hear it.
const fire = (target, type) => { const event = { type, target, bubbles: true, preventDefault() {}, stopPropagation() {} };
  for (let node = target; node; node = node.parentElement) { event.currentTarget = node; for (const l of [...(node.listeners[type] ?? [])]) l.call(node, event); } };
// A user's click on a checkbox flips it, then dispatches click, input and change.
const toggle = (box) => { box.checked = !box.checked; for (const type of ["click", "input", "change"]) fire(box, type); };
const descend = (n) => (n?.nodeType === 1 ? [n, ...n.children.flatMap(descend)] : []);
const section = () => byId.get("profile-section");
const cardKeys = () => [...(byId.get("video-cards")?.innerHTML ?? "").matchAll(/data-video-key="([^"]+)"/g)].map((m) => m[1]);
await import(process.env.BUNDLE);
await settle();
const report = { feedAtStart: feed.map((f) => ({ ...f })), heldAtStart: release !== null };
fire(byId.get("show-profile-header"), "click");
await settle();
if (process.env.PROFILE_STATE === "issued-key") {
  fire(descend(section()).find((n) => n.tagName === "BUTTON" && n.textContent === "Create profile"), "click");
  await settle();
}
report.intro = section().children[0]?.textContent ?? null;
const boxes = descend(section()).filter((n) => n.tagName === "INPUT" && n.type === "checkbox");
report.checkboxes = boxes.map((b) => ({ checked: b.checked }));
if (boxes.length) {
  toggle(boxes[0]);
  await settle();
}
report.afterOff = { feed: feed.map((f) => ({ ...f })), cards: cardKeys() };
release?.();
await settle();
report.afterRelease = { cards: cardKeys(), firstBodyRead };
if (boxes.length) {
  toggle(boxes[0]);
  await settle();
}
report.afterOn = { feed: feed.map((f) => ({ ...f })), cards: cardKeys() };
report.rejections = rejections;
process.stdout.write(JSON.stringify(report) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def home_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("home")
    run = subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "videos" / "index.ts"), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    (out / "runner.mjs").write_text(HOME_RUNNER)
    return out


def _rows(tag: str) -> list[dict]:
    # views and likes on the row keep the page from fetching live stats from the instance.
    return [{"video_id": f"{tag}{i}", "video_uuid": f"uuid-{tag}{i}", "instance_domain": "peer.example", "title": f"{tag} {i}", "views": 1, "likes": 1} for i in range(1, 4)]


def _keys(rows: list[dict]) -> list[str]:
    return [f"{row['instance_domain']}::{row['video_uuid']}" for row in rows]


# The first load's page, the page fetched after turning the filter off, and the one after turning it back on.
FIRST, TURNED_OFF, TURNED_ON = _rows("a"), _rows("b"), _rows("c")
PROFILE_STATES = {
    "keyless": ({}, "No profile."),
    "key-holding": ({PROFILE_KEY: "K" * 43}, "This browser holds a profile key."),
    "issued-key": ({}, "This is the only copy of your key."),
}
HOME_FEED = ["recommendations"]


@pytest.mark.parametrize("state", PROFILE_STATES)
def test_the_checked_profile_checkbox_reloads_the_home_feed_under_each_new_setting_and_shows_that_page(home_bundle, state):
    storage, intro = PROFILE_STATES[state]
    proc = subprocess.run(
        ["node", str(home_bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(home_bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps(storage),
             "PAGES": json.dumps([FIRST, TURNED_OFF, TURNED_ON]), "ISSUED_KEY": "I" * 43, "PROFILE_STATE": state},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])

    # control: the page made its first feed request filtered and its response is held, and the modal rendered the state under test, so the checkbox is looked for in that branch
    assert page["feedAtStart"] == [{"mode": HOME_FEED, "nsfw": []}] and page["heldAtStart"] is True, page
    assert (page["intro"] or "").startswith(intro), (page["intro"], page["rejections"])
    # A checkbox left out of this branch, or built unchecked, fails here.
    assert page["checkboxes"] == [{"checked": True}], (page["checkboxes"], page["rejections"])
    # Unchecking reloads the same feed once, now opted in; a handler that saves without reloading adds no request, and a URL built from a setting captured at page load carries no nsfw.
    assert page["afterOff"]["feed"] == [{"mode": HOME_FEED, "nsfw": []}, {"mode": HOME_FEED, "nsfw": ["1"]}], (page["afterOff"], page["rejections"])
    # control: the held first page reached the page after the toggle's page had rendered, so the stale result was there to be dropped
    assert page["afterRelease"]["firstBodyRead"] is True, page["afterRelease"]
    # A load that renders whichever response arrives last shows the first page's keys here.
    assert page["afterRelease"]["cards"] == _keys(TURNED_OFF), (page["afterOff"]["cards"], page["afterRelease"], page["rejections"])
    # Checking it again reloads filtered; a handler that always turns the filter off sends nsfw=1 again.
    assert page["afterOn"]["feed"][2:] == [{"mode": HOME_FEED, "nsfw": []}], page["afterOn"]
    assert page["afterOn"]["cards"] == _keys(TURNED_ON), (page["afterOn"], page["rejections"])


# --- follow controls on the home cards, on a recording DOM that parses innerHTML ---

KEY_STORAGE = {"profileKey:v1": "K" * 43}
NEEDS_PROFILE = "Following needs a profile. Create one from the Profile button."
LIMIT_ERROR = "Follow limit reached (1000)"

# A recording DOM for node: innerHTML is parsed into elements, so a page's delegated click handler, `closest`, `querySelector(All)` and `dataset` work on the cards and rows it renders, and a redraw replaces element objects (each carries a `uid`). A selector outside the small supported grammar throws, so it surfaces as a rejection rather than matching nothing.
DOM_JS = r"""
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const decode = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (m, e) => { const l = e.toLowerCase();
  if (l[0] === "#") return String.fromCodePoint(l[1] === "x" ? parseInt(l.slice(2), 16) : parseInt(l.slice(1), 10));
  return { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" }[l]; });
const escapeText = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const kebab = (k) => k.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
const textNode = (v) => ({ nodeType: 3, textContent: String(v), parentElement: null });
let uid = 0;
const adopt = (parent, nodes) => { for (const n of nodes) { if (n.parentElement && n.parentElement !== parent) n.parentElement.childNodes.splice(n.parentElement.childNodes.indexOf(n), 1); n.parentElement = parent; } return nodes; };
const element = (tag) => {
  const el = { nodeType: 1, tagName: tag.toUpperCase(), localName: tag.toLowerCase(), uid: ++uid, attrs: {}, childNodes: [], parentElement: null, listeners: {}, value: "", checked: false, style: {}, root: false, readOnly: false, placeholder: "",
    get children() { return el.childNodes.filter((n) => n.nodeType === 1); },
    get firstElementChild() { return el.children[0] ?? null; },
    get nextElementSibling() { const s = el.parentElement?.children ?? []; return s[s.indexOf(el) + 1] ?? null; },
    get previousElementSibling() { const s = el.parentElement?.children ?? []; return s[s.indexOf(el) - 1] ?? null; },
    get id() { return el.attrs.id ?? ""; }, set id(v) { el.attrs.id = String(v); },
    get className() { return el.attrs.class ?? ""; }, set className(v) { el.attrs.class = String(v); },
    get hidden() { return "hidden" in el.attrs; }, set hidden(v) { if (v) el.attrs.hidden = ""; else delete el.attrs.hidden; },
    get disabled() { return "disabled" in el.attrs; }, set disabled(v) { if (v) el.attrs.disabled = ""; else delete el.attrs.disabled; },
    get type() { return el.attrs.type ?? ""; }, set type(v) { el.attrs.type = String(v); },
    get href() { return el.attrs.href ?? ""; }, set href(v) { el.attrs.href = String(v); },
    get title() { return el.attrs.title ?? ""; }, set title(v) { el.attrs.title = String(v); },
    get textContent() { return el.childNodes.map((n) => n.textContent).join(""); },
    set textContent(v) { el.setChildren(v == null || v === "" ? [] : [textNode(v)]); },
    get innerHTML() { return el.childNodes.map(serialize).join(""); },
    set innerHTML(v) { el.setChildren(parse(String(v))); },
    get outerHTML() { return serialize(el); },
    set outerHTML(v) { const parent = el.parentElement; if (!parent) throw new Error("outerHTML set on a detached node");
      const nodes = parse(String(v)); parent.childNodes.splice(parent.childNodes.indexOf(el), 1, ...nodes); for (const n of nodes) n.parentElement = parent; el.parentElement = null; },
    get isConnected() { for (let n = el; n; n = n.parentElement) if (n.root) return true; return false; },
    setChildren: (nodes) => { for (const n of el.childNodes) n.parentElement = null; el.childNodes = adopt(el, nodes); },
    classList: { add: (...c) => { const s = new Set(el.className.split(/\s+/).filter(Boolean)); c.forEach((x) => s.add(x)); el.className = [...s].join(" "); },
      remove: (...c) => { el.className = el.className.split(/\s+/).filter((x) => x && !c.includes(x)).join(" "); },
      contains: (c) => el.className.split(/\s+/).includes(c),
      toggle: (c, force) => { const on = force ?? !el.classList.contains(c); if (on) el.classList.add(c); else el.classList.remove(c); return on; } },
    append: (...items) => { const nodes = items.map((i) => (typeof i === "string" ? textNode(i) : i)); adopt(el, nodes); el.childNodes.push(...nodes); },
    prepend: (...items) => { const nodes = items.map((i) => (typeof i === "string" ? textNode(i) : i)); adopt(el, nodes); el.childNodes.unshift(...nodes); },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { el.setChildren([]); el.append(...items); },
    remove: () => { const p = el.parentElement; if (p) { p.childNodes.splice(p.childNodes.indexOf(el), 1); el.parentElement = null; } },
    insertAdjacentHTML: (position, markup) => { const nodes = parse(String(markup)); const where = String(position).toLowerCase();
      if (where === "beforeend" || where === "afterbegin") { adopt(el, nodes); if (where === "beforeend") el.childNodes.push(...nodes); else el.childNodes.unshift(...nodes); return; }
      const p = el.parentElement; if (!p) throw new Error(`insertAdjacentHTML ${position} on a detached node`); adopt(p, nodes);
      p.childNodes.splice(p.childNodes.indexOf(el) + (where === "afterend" ? 1 : 0), 0, ...nodes); },
    setAttribute: (n, v) => { el.attrs[String(n).toLowerCase()] = String(v); },
    removeAttribute: (n) => { delete el.attrs[String(n).toLowerCase()]; },
    hasAttribute: (n) => String(n).toLowerCase() in el.attrs, getAttribute: (n) => el.attrs[String(n).toLowerCase()] ?? null,
    toggleAttribute: (n, force) => { const on = force ?? !el.hasAttribute(n); if (on) el.setAttribute(n, ""); else el.removeAttribute(n); return on; },
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); }, removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    matches: (sel) => matches(el, sel), closest: (sel) => { for (let n = el; n; n = n.parentElement) if (matches(n, sel)) return n; return null; },
    querySelectorAll: (sel) => descendants(el).filter((n) => matches(n, sel)), querySelector: (sel) => el.querySelectorAll(sel)[0] ?? null,
    getBoundingClientRect: () => ({ top: 100000, bottom: 100000, left: 0, right: 0, width: 0, height: 0 }),
    focus() {}, blur() {}, select() {}, scrollIntoView() {},
  };
  el.dataset = new Proxy({}, { get: (_, k) => (typeof k === "string" ? el.attrs["data-" + kebab(k)] : undefined),
    set: (_, k, v) => { el.attrs["data-" + kebab(String(k))] = String(v); return true; }, deleteProperty: (_, k) => { delete el.attrs["data-" + kebab(String(k))]; return true; } });
  return el;
};
const descendants = (el) => el.children.flatMap((c) => [c, ...descendants(c)]);
const TOKEN = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>|([^<]+)|(<)/g;
const ATTR = /([^\s"'>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
const parse = (markup) => {
  const top = { childNodes: [], localName: null };
  const stack = [top];
  for (const m of markup.matchAll(TOKEN)) {
    const open = stack[stack.length - 1];
    const parent = open === top ? null : open;
    if (m[1]) { const i = stack.map((n) => n.localName).lastIndexOf(m[1].toLowerCase()); if (i > 0) stack.length = i; continue; }
    if (m[2]) { const el = element(m[2]); for (const a of m[3].matchAll(ATTR)) el.attrs[a[1].toLowerCase()] = decode(a[2] ?? a[3] ?? a[4] ?? "");
      el.parentElement = parent; open.childNodes.push(el); if (!m[4] && !VOID.has(el.localName)) stack.push(el); continue; }
    if (m[5] !== undefined || m[6]) { const t = textNode(decode(m[5] ?? "<")); t.parentElement = parent; open.childNodes.push(t); }
  }
  return top.childNodes;
};
const serialize = (n) => (n.nodeType !== 1 ? escapeText(n.textContent) : `<${n.localName}${Object.entries(n.attrs).map(([k, v]) => ` ${k}="${escapeText(v).replace(/"/g, "&quot;")}"`).join("")}>`
  + (VOID.has(n.localName) ? "" : `${n.childNodes.map(serialize).join("")}</${n.localName}>`));
const splitTop = (s, sep) => { const out = []; let depth = 0, quote = null, cur = "";
  for (const ch of s) { if (quote) { if (ch === quote) quote = null; cur += ch; continue; } if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === "[") depth += 1; if (ch === "]") depth -= 1; if (depth === 0 && sep.test(ch)) { out.push(cur); out.push(ch); cur = ""; continue; } cur += ch; }
  out.push(cur); return out; };
const COMPOUND = /#([\w-]+)|\.([\w-]+)|\[\s*([\w-]+)\s*(?:([\^$*~|]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]+))\s*)?\]|([a-zA-Z][\w-]*|\*)/y;
const compound = (src) => { const tests = []; COMPOUND.lastIndex = 0; let m;
  while (COMPOUND.lastIndex < src.length && (m = COMPOUND.exec(src))) {
    const [, id, cls, attr, op, dq, sq, bare, tag] = m;
    if (id) tests.push((n) => n.attrs.id === id);
    else if (cls) tests.push((n) => (n.attrs.class ?? "").split(/\s+/).includes(cls));
    else if (attr) { const name = attr.toLowerCase(), v = dq ?? sq ?? bare;
      tests.push((n) => { const a = n.attrs[name]; if (a === undefined) return false; if (!op) return true;
        return op === "=" ? a === v : op === "^=" ? a.startsWith(v) : op === "$=" ? a.endsWith(v) : op === "*=" ? a.includes(v) : op === "~=" ? a.split(/\s+/).includes(v) : a === v || a.startsWith(v + "-"); }); }
    else if (tag !== "*") { const name = tag.toLowerCase(); tests.push((n) => n.localName === name); }
  }
  if (COMPOUND.lastIndex !== src.length || !src) throw new Error(`selector not stubbed: ${src}`);
  return (n) => n.nodeType === 1 && tests.every((t) => t(n)); };
const compiled = new Map();
const compile = (sel) => { if (compiled.has(sel)) return compiled.get(sel);
  const alternatives = splitTop(sel, /,/).filter((_, i) => i % 2 === 0).map((alt) => {
    const pieces = splitTop(alt.trim().replace(/\s*>\s*/g, ">"), /[\s>]/); const parts = [];
    for (let i = 0; i < pieces.length; i += 2) parts.push({ test: compound(pieces[i]), comb: i ? pieces[i - 1] : null });
    return parts; });
  compiled.set(sel, alternatives); return alternatives; };
const matchParts = (n, parts, i) => { if (!parts[i].test(n)) return false; if (i === 0) return true;
  if (parts[i].comb === ">") return n.parentElement ? matchParts(n.parentElement, parts, i - 1) : false;
  for (let a = n.parentElement; a; a = a.parentElement) if (matchParts(a, parts, i - 1)) return true; return false; };
const matches = (n, sel) => n?.nodeType === 1 && compile(sel).some((parts) => matchParts(n, parts, parts.length - 1));
"""

# One harness for the home, video and channels pages. Elements are created on first lookup by id (SEEDS gives some a tag, text and disabled/hidden state from the page's HTML). `fetch` records every request and answers from ANSWERS, keyed "METHOD /path": a list is consumed in order (a call past its end gets 500 "not scripted"), an object repeats; anything else gets ANSWERS.default. A path in HELD is answered only once the follow list has been answered (or after 300 ms when it never is), so the page renders with its follow list loaded. A click reaches the listeners, bubbling, only while the node is neither disabled nor hidden, as for a user.
PAGE_RUNNER = DOM_JS + r"""
const env = process.env;
const memory = (seed) => { const s = new Map(Object.entries(seed)); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory(JSON.parse(env.STORAGE));
globalThis.sessionStorage = memory({});
globalThis.window = { location: { origin: env.BASE, pathname: env.PATHNAME, search: env.SEARCH }, localStorage, sessionStorage, innerHeight: 800, scrollY: 0,
  addEventListener() {}, removeEventListener() {}, confirm: () => true, setTimeout, clearTimeout, history: { pushState() {}, replaceState() {} } };
const seeds = JSON.parse(env.SEEDS);
const byId = new Map();
const rootEl = (id) => { if (!byId.has(id)) { const s = seeds[id]; const el = element(s?.tag ?? "div"); el.root = true; el.attrs.id = id;
  if (s?.disabled) el.disabled = true; if (s?.hidden) el.hidden = true; if (s?.text) el.textContent = s.text; byId.set(id, el); } return byId.get(id); };
Object.keys(seeds).forEach(rootEl);
const everything = () => [...byId.values()].flatMap((r) => [r, ...descendants(r)]);
globalThis.document = { title: "", body: element("body"), documentElement: { scrollHeight: 100000 }, getElementById: rootEl, createElement: (t) => element(t), createTextNode: (v) => textNode(v),
  querySelector: (s) => everything().find((n) => matches(n, s)) ?? null, querySelectorAll: (s) => everything().filter((n) => matches(n, s)), addEventListener() {} };
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
const answers = JSON.parse(env.ANSWERS);
const held = new Set(JSON.parse(env.HELD));
const requests = [];
let openGate;
const gate = new Promise((resolve) => { openGate = resolve; });
setTimeout(() => openGate(), 300);
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), env.BASE);
  const method = String(init?.method ?? "GET").toUpperCase();
  let body = null;
  try { body = init?.body ? JSON.parse(init.body) : null; } catch { body = String(init.body); }
  requests.push({ method, path: url.pathname, query: Object.fromEntries(url.searchParams), body });
  if (held.has(url.pathname)) await gate;
  const scripted = answers[`${method} ${url.pathname}`];
  const answer = Array.isArray(scripted) ? (scripted.shift() ?? { status: 500, body: { error: "not scripted" } }) : scripted ?? answers.default;
  if (method === "GET" && url.pathname === "/api/profile/follows") setTimeout(() => openGate(), 30);
  const status = answer.status ?? 200;
  return new Response(status === 204 ? null : JSON.stringify(answer.body ?? {}), { status, headers: { "content-type": "application/json" } });
};
const rejections = [];
process.on("unhandledRejection", (r) => { rejections.push(String((r && r.stack) || r)); });
const settle = async (n) => { for (let i = 0; i < n; i += 1) await new Promise((r) => setTimeout(r, 10)); };
const click = (target) => { if (target.disabled || target.hidden) return false; let stopped = false;
  const event = { type: "click", target, bubbles: true, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() { stopped = true; } };
  for (let node = target; node && !stopped; node = node.parentElement) { event.currentTarget = node;
    for (const l of [...(node.listeners.click ?? [])]) { try { l.call(node, event); } catch (e) { rejections.push(String((e && e.stack) || e)); } } }
  return true; };
const label = (n) => n.textContent.replace(/\s+/g, " ").trim();
const under = (scope) => [scope, ...descendants(scope)];
const buttons = (scope) => under(scope).filter((n) => n.tagName === "BUTTON");
const texts = (scope) => under(scope).map(label).filter(Boolean);
const LONG = /^(Follow|Unfollow) (channel|account)$/;
const followLabels = (nodes) => { const out = { channel: [], account: [] }; for (const b of nodes.filter((n) => n.tagName === "BUTTON")) { const m = label(b).match(LONG); if (m) out[m[2]].push(label(b)); } return out; };
const cards = () => rootEl("video-cards").querySelectorAll("article");
const rows = () => rootEl("channels-body").querySelectorAll("tr");
const names = JSON.parse(env.ROW_NAMES);
const rowName = (tr) => names.filter((n) => tr.textContent.includes(n));
const snapshot = () => {
  if (env.PAGE === "home") return { cards: cards().map((a) => ({ uid: a.uid, key: a.attrs["data-video-key"] ?? null, follow: followLabels(under(a)), status: label(a.querySelector(".card-action-status") ?? textNode("")) })), texts: texts(rootEl("video-cards")) };
  if (env.PAGE === "channels") return { rows: rows().map((tr) => ({ names: rowName(tr), follow: buttons(tr).map(label).filter((t) => /^(Follow|Unfollow)$/.test(t)), texts: texts(tr) })) };
  return { follow: followLabels(everything()), texts: everything().map(label).filter(Boolean) };
};
const scopeOf = (step) => {
  if (step.card) return cards().filter((a) => a.attrs["data-video-key"] === step.card);
  if (step.row) return rows().filter((tr) => rowName(tr).includes(step.row));
  return [...byId.values()];
};
await import(env.BUNDLE);
await settle(60);
const snapshots = [snapshot()];
const steps = [];
for (const step of JSON.parse(env.STEPS)) {
  const before = requests.length;
  const scopes = scopeOf(step);
  const targets = [...new Set(scopes.flatMap((s) => buttons(s)).filter((b) => label(b) === step.click))];
  const dispatched = targets.length === 1 ? click(targets[0]) : false;
  await settle(40);
  steps.push({ ...step, scopes: scopes.length, matches: targets.length, dispatched, requests: requests.slice(before) });
  snapshots.push(snapshot());
}
process.stdout.write(JSON.stringify({ snapshots, steps, requests, rejections }) + "\n", () => process.exit(0));
"""


def _esbuild(entry: Path, out: Path, base: str = BASE, check: bool = True) -> bool:
    run = subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0 or not check, run.stderr[-2000:]
    return run.returncode == 0


def _node(runner: Path, env: dict[str, str]) -> str:
    proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=120, env={"PATH": os.environ.get("PATH", ""), **env})
    assert proc.returncode == 0, proc.stderr[-4000:]
    return proc.stdout


@pytest.fixture(scope="module")
def pages(tmp_path_factory) -> Path:
    """The home page module bundled as `home.mjs`, beside the follow-control runner."""
    out = tmp_path_factory.mktemp("follow_pages")
    _esbuild(FRONTEND / "src" / "pages" / "videos" / "index.ts", out / "home.mjs")
    (out / "runner.mjs").write_text(PAGE_RUNNER)
    return out


def _page(pages: Path, page: str, *, storage: dict, answers: dict, steps: list[dict] = (), search: str = "", pathname: str = "/", held: list[str] = (), seeds: dict | None = None, row_names: list[str] = ()) -> dict:
    out = _node(pages / "runner.mjs", {
        "BASE": BASE, "BUNDLE": str(pages / f"{page}.mjs"), "PAGE": page, "STORAGE": json.dumps(storage), "SEARCH": search, "PATHNAME": pathname,
        "ANSWERS": json.dumps({"default": {"status": 404, "body": {}}, **answers}), "HELD": json.dumps(list(held)), "SEEDS": json.dumps(seeds or {}),
        "STEPS": json.dumps(list(steps)), "ROW_NAMES": json.dumps(list(row_names)),
    })
    return json.loads(out.splitlines()[-1])


def _follows_paths(requests: list[dict]) -> list[str]:
    return [f"{r['method']} {r['path']}" for r in requests if r["path"].startswith("/api/profile/follows")]


def _sent(step: dict) -> list[dict]:
    """The follow-route requests a step made; the page's other loads can land in a step's window and are not what it is about."""
    return [r for r in step["requests"] if r["path"].startswith("/api/profile/follows")]


def _key_fields(body: dict | None) -> dict:
    return {k: (body or {}).get(k) for k in ("kind", "instance_domain", "channel_id", "account_url")}


def _video_form(body: dict | None) -> dict:
    # The Client refuses a body naming a video and a channel together, so the channel fields must be absent.
    return {k: (body or {}).get(k) for k in ("kind", "uuid", "host", "instance_domain", "channel_id")}


def _channel(host: str, channel_id: str, label: str) -> dict:
    return {"kind": "channel", "instance_domain": host, "channel_id": channel_id, "account_url": "", "label": label, "created_at": 1}


def _account(account_url: str, label: str) -> dict:
    return {"kind": "account", "instance_domain": "", "channel_id": "", "account_url": account_url, "label": label, "created_at": 1}


PEER, OTHER = "peer.example", "other.example"
ALICE, BOB = "https://peer.example/accounts/alice", "https://peer.example/accounts/bob"
OTHER_ALICE = "https://other.example/accounts/alice"


def _card(n: int, host: str, channel_id: str, account_url: str) -> dict:
    # views and likes keep the page from fetching live stats from the instance.
    return {"video_id": f"v{n}", "video_uuid": f"uuid-{n}", "instance_domain": host, "channel_id": channel_id, "account_url": account_url, "title": f"video {n}", "views": 1, "likes": 1}


# Two cards of the followed channel, one of the followed account, and one whose channel_id matches the followed channel on another host.
CARDS = [_card(1, PEER, "ch-followed", ALICE), _card(2, PEER, "ch-followed", ALICE), _card(3, PEER, "ch-other", BOB), _card(4, OTHER, "ch-followed", OTHER_ALICE)]
K1, K2, K3, K4 = (f"{c['instance_domain']}::{c['video_uuid']}" for c in CARDS)
HOME_FOLLOWS = [_channel(PEER, "ch-followed", "Followed channel"), _account(BOB, "Bob")]


def _labels(snapshot: dict) -> dict[str, tuple]:
    """Each card's follow buttons as (channel labels, account labels), by card key."""
    return {c["key"]: (c["follow"]["channel"], c["follow"]["account"]) for c in snapshot["cards"]}


def _uids(snapshot: dict) -> list[int]:
    return [c["uid"] for c in snapshot["cards"]]


def _status(snapshot: dict, key: str) -> str:
    return next(c["status"] for c in snapshot["cards"] if c["key"] == key)


def test_home_cards_are_labelled_from_the_loaded_follow_list_and_a_toggle_relabels_every_card_of_its_source_in_place(pages):
    answers = {
        "GET /api/profile/follows": {"body": {"follows": HOME_FOLLOWS}},
        "POST /recommendations": [{"body": {"rows": CARDS}}],
        "POST /api/profile/follows/remove": [{"status": 204}],
        "POST /api/profile/follows": [{"status": 201, "body": {"follow": _account(ALICE, "Alice")}}, {"status": 400, "body": {"error": LIMIT_ERROR}}],
    }
    page = _page(pages, "home", storage=KEY_STORAGE, answers=answers, held=["/recommendations"],
                 steps=[{"card": K1, "click": "Unfollow channel"}, {"card": K2, "click": "Follow account"}, {"card": K3, "click": "Follow channel"}])
    loaded, unfollowed, followed, refused = page["snapshots"]
    steps = page["steps"]

    # control: the feed rendered all four cards with nothing escaping the page
    assert [c["key"] for c in loaded["cards"]] == [K1, K2, K3, K4], (loaded, page["rejections"])
    # Without the list every card reads "Follow …"; a channel lookup keyed by channel_id alone also marks card 4, on another host.
    assert _labels(loaded) == {
        K1: (["Unfollow channel"], ["Follow account"]), K2: (["Unfollow channel"], ["Follow account"]),
        K3: (["Follow channel"], ["Unfollow account"]), K4: (["Follow channel"], ["Follow account"]),
    }, (loaded, page["rejections"])  # C2
    # Unfollowing card 1's channel sends its key and relabels both cards of that channel; card 4 shares only the channel_id.
    assert steps[0]["dispatched"] is True and [(r["method"], r["path"], _key_fields(r["body"])) for r in _sent(steps[0])] == [
        ("POST", "/api/profile/follows/remove", {"kind": "channel", "instance_domain": PEER, "channel_id": "ch-followed", "account_url": ""})], steps[0]  # C2
    assert _labels(unfollowed) == {
        K1: (["Follow channel"], ["Follow account"]), K2: (["Follow channel"], ["Follow account"]),
        K3: (["Follow channel"], ["Unfollow account"]), K4: (["Follow channel"], ["Follow account"]),
    }, (unfollowed, page["rejections"])  # C2
    # Following card 2's account names the video, and relabels card 1 too (same account), not card 4 (another account URL).
    assert steps[1]["dispatched"] is True and [(r["method"], r["path"], _video_form(r["body"])) for r in _sent(steps[1])] == [
        ("POST", "/api/profile/follows", {"kind": "account", "uuid": "uuid-2", "host": PEER, "instance_domain": None, "channel_id": None})], steps[1]  # C2
    assert _labels(followed) == {
        K1: (["Follow channel"], ["Unfollow account"]), K2: (["Follow channel"], ["Unfollow account"]),
        K3: (["Follow channel"], ["Unfollow account"]), K4: (["Follow channel"], ["Follow account"]),
    }, (followed, page["rejections"])  # C2
    # A follow the Client refuses leaves the label as it was and says why; an optimistic flip reads "Unfollow channel".
    assert steps[2]["dispatched"] is True and [r["path"] for r in _sent(steps[2])] == ["/api/profile/follows"], steps[2]
    assert _labels(refused) == _labels(followed) and _status(refused, K3) == LIMIT_ERROR, (refused, page["rejections"])  # C2
    # No toggle redrew a card: `card.outerHTML =` or a grid redraw replaces the element objects.
    assert _uids(unfollowed) == _uids(followed) == _uids(refused) == _uids(loaded), [_uids(s) for s in page["snapshots"]]  # C2
    # One list fetch for the page: the toggles change the loaded list rather than reading it again.
    assert _follows_paths(page["requests"]).count("GET /api/profile/follows") == 1, page["requests"]  # C2


def test_keyless_home_cards_read_follow_and_a_click_sends_nothing_and_says_following_needs_a_profile(pages):
    page = _page(pages, "home", storage={}, answers={"POST /recommendations": [{"body": {"rows": CARDS}}]}, held=["/recommendations"],
                 steps=[{"card": K1, "click": "Block channel"}, {"card": K1, "click": "Follow channel"}, {"card": K3, "click": "Follow account"}])
    loaded, blocked, channel, account = page["snapshots"]

    # control: the cards rendered and a card click reaches the page's handler, which answers a keyless block with its own wording (observed today)
    assert [c["key"] for c in loaded["cards"]] == [K1, K2, K3, K4], (loaded, page["rejections"])
    assert _status(blocked, K1) == "Blocking needs a profile. Create one from the Profile button.", (blocked, page["rejections"])
    assert all(labels == (["Follow channel"], ["Follow account"]) for labels in _labels(loaded).values()), loaded  # C2
    assert page["steps"][1]["dispatched"] and _status(channel, K1) == NEEDS_PROFILE, (channel, page["rejections"])  # C2
    assert page["steps"][2]["dispatched"] and _status(account, K3) == NEEDS_PROFILE, (account, page["rejections"])  # C2
    assert _labels(account) == _labels(loaded), account  # C2
    # Nothing reaches the follow routes, the list included.
    assert _follows_paths(page["requests"]) == [], page["requests"]  # C2


def _feed_requests(page: dict) -> list[dict]:
    return [r for r in page["requests"] if r["path"] == "/recommendations"]


def test_keyless_following_mode_shows_following_needs_a_profile_and_requests_no_feed(pages):
    control = _page(pages, "home", storage={}, search="?mode=trending", answers={"POST /recommendations": [{"body": {"rows": CARDS}}]})
    page = _page(pages, "home", storage={}, search="?mode=following", answers={"POST /recommendations": [{"body": {"rows": CARDS}}]})

    # control: keyless, this harness's home page requests its feed for the mode in ?mode=
    assert [r["query"].get("mode") for r in _feed_requests(control)] == ["trending"], control["requests"]
    # Today ?mode=following falls back to recommendations and requests it (observed).
    assert _feed_requests(page) == [], page["requests"]  # C2
    assert NEEDS_PROFILE in page["snapshots"][0]["texts"] and page["snapshots"][0]["cards"] == [], (page["snapshots"][0], page["rejections"])  # C2


def test_keyed_following_mode_walks_an_empty_page_by_its_cursor_to_the_rows_and_stops_without_a_cursor(pages):
    shown = CARDS[:2]
    answers = {"GET /api/profile/follows": {"body": {"follows": HOME_FOLLOWS}}, "POST /recommendations": [{"body": {"rows": [], "cursor": "c1"}}, {"body": {"rows": shown}}]}
    page = _page(pages, "home", storage=KEY_STORAGE, search="?mode=following", answers=answers, held=["/recommendations"])
    feed = _feed_requests(page)

    # createFeedPager stops at the empty first page and shows "No videos found." after one request; a third request reads 500 "not scripted".
    assert [(r["query"].get("mode"), (r["body"] or {}).get("cursor")) for r in feed] == [("following", None), ("following", "c1")], page["requests"]  # C1
    assert [c["key"] for c in page["snapshots"][0]["cards"]] == [K1, K2], (page["snapshots"][0], page["rejections"])  # C1
