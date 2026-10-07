"""Tag chips are links to the search page's results for their tag, outside every video link, and a card's chip row fits itself to one line behind a `+N` marker.

`components/video-card.ts` runs in node on two esbuild bundles, a production one (DEV false) and a dev one (DEV true). A runner calls its exports with JSON arguments, and a missing export or a throw comes back as data. Markup is read with Python's `html.parser`, which nests an `<a>` inside another exactly as written, so a chip written into a video link reads as inside it. Every href is parsed with `urllib.parse`, independently of the module.

Links (C1):
- `tagSearchUrl("a b&c")` is `/search.html?tag=a+b%26c`, with or without an apiParam in production. In dev an apiParam adds `api` and no apiParam adds nothing.
- `tagSearchUrl` is null for "" and "   ", and for 65 code points of ASCII and of emoji. It links 64 of either; 64 emoji are 128 UTF-16 units.
- `renderTagChips` gives one chip for `["solo"]` and `""` for undefined, null, `[]` and `["", "   "]`.
- For `["zeta", "Lo-fi & Chill", "   ", 65 × "a", "alpha", 64 emoji]` the chips are `<a>` elements reading zeta, Lo-fi & Chill, alpha and the emoji, in that order. Each href searches only its tag and equals `tagSearchUrl` of it. In dev, with an apiParam, each href also carries `api` and equals the dev `tagSearchUrl(tag, api)`. The chips share one `.card-tags` parent, whose only other element carries `hidden` and is its last child, after all four chips.
- A `<script>` tag and a tag with a `"` read back as their own text and as their own `tag` parameter. No script element or `onmouseover` attribute appears, and no element has a `style` attribute.
- `renderVideoCard`, with actions and an apiParam, shows both chips as links without `api`, under no `<a>`, in a `.card-tags` row that is a later child of the card than `a.video-link`.
- The video page module, run in node on copies of the active page harnesses with `?api=` in its URL (production build), works as follows. The up-next cards are `div.similar-card-item` elements keyed by `data-video-key`, holding `a.similar-card-link` and then a `.card-tags` row. The row's chips are links without `api`, under no `<a>`, and a blank tag gets none. The taxonomy's `alpha` and `a b&c` are `A` chips linking to `/search.html?tag=alpha` and `/search.html?tag=a+b%26c`, and a blank or a 65-code-point tag is a `SPAN` with no href.

Fit (C2), on the recording DOM of the video page harness with a browser's observers and a layout stubbed. A row is as wide as its card; a chip is 50px and any other element in the row 30px, either 0 while hidden. `observeTagRows` watches the container before any card arrives. A five-chip card arrives by innerHTML at 160px; a two-chip card and a second five-chip card then arrive by insertAdjacentHTML, both at 160px.
- The first five-chip row shows t1 and t2, a shown marker reads `+3` with `aria-label="3 more tags"`, all five chips are still in the row, and its scrollWidth fits its width.
- At 210px it shows t1 to t3 with `+2` / "2 more tags". At 300px it shows all five and the marker is hidden. Back at 160px it shows t1 and t2 with `+3` again.
- At the widths the stub fits exactly it keeps what fits: 130px shows t1 and t2 with `+3`, 180px t1 to t3 with `+2`, and 250px all five with the marker hidden. At 70px no chip fits beside the marker: none shows, and the marker reads `+5` / "5 more tags".
- The appended five-chip row shows t1 and t2 with `+3` / "3 more tags". The appended two-chip row shows both chips with its marker hidden, while the first five-chip row's marker shows.

Page wiring (C2): the feed (`pages/videos/index.ts`, `#video-cards`), the search page (`pages/search/index.ts` at `?q=x`, `#search-results`) and the video page's up-next (`#similar-videos`) each run, production build, on that same DOM, observers and layout, with `fetch` stubbed. Each page's endpoint answers with one row carrying t1 to t5, and its card is 160px wide. On each page, the card's row shows t1 and t2 with `+3` / "3 more tags". Widened to 300px, it shows all five with the marker hidden.
"""
from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
API = "http://api.example"

# Calls each named export with JSON arguments; a missing export or a throw is reported as data, so the assertion that reads it is the one that fails.
CALL_RUNNER = """
const m = await import(process.env.BUNDLE);
const results = JSON.parse(process.env.CALLS).map(([name, ...args]) => {
  if (typeof m[name] !== "function") return { error: `${name} is not exported` };
  try { const value = m[name](...args); return value === undefined ? { undefined: true } : { value }; } catch (error) { return { error: String(error) }; }
});
process.stdout.write(JSON.stringify(results) + "\\n");
"""

# The recording DOM of tests/active/test_frontend_video_page.py (DOM_JS), with what a fit needs from a browser added: elements are HTMLElement instances, childList changes reach MutationObservers in a microtask, a ResizeObserver reports a target's width on its first delivery and whenever it changes, and a small layout gives widths.
FIT_RUNNER = r"""
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const decode = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (m, e) => { const l = e.toLowerCase();
  if (l[0] === "#") return String.fromCodePoint(l[1] === "x" ? parseInt(l.slice(2), 16) : parseInt(l.slice(1), 10));
  return { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" }[l]; });
const escapeText = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const kebab = (k) => k.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
class Node {}
class Element extends Node {}
class HTMLElement extends Element {}
Object.assign(globalThis, { Node, Element, HTMLElement });
const errors = [];
const textNode = (v) => ({ nodeType: 3, textContent: String(v), parentElement: null });
const mutationObservers = [];
let mutationsQueued = false;
const notify = (target, added, removed) => {
  if (!added.length && !removed.length) return;
  for (const mo of mutationObservers) {
    const watching = mo.watched.some(({ node, options }) => { if (!options.childList) return false; for (let n = target; n; n = n.parentElement) if (n === node) return n === target || Boolean(options.subtree); return false; });
    if (watching) mo.records.push({ type: "childList", target, addedNodes: [...added], removedNodes: [...removed] });
  }
  if (mutationsQueued) return;
  mutationsQueued = true;
  queueMicrotask(() => { mutationsQueued = false;
    for (const mo of mutationObservers) { const records = mo.records.splice(0); if (records.length) { try { mo.callback(records, mo); } catch (e) { errors.push(String((e && e.stack) || e)); } } } });
};
globalThis.MutationObserver = class { constructor(callback) { this.callback = callback; this.watched = []; this.records = []; mutationObservers.push(this); }
  observe(node, options = {}) { this.watched.push({ node, options }); } disconnect() { this.watched = []; this.records = []; } takeRecords() { return this.records.splice(0); } };
// Layout: a card's tag row is as wide as its card (cardWidths, by data-video-key); in a row a tag chip is 50px and any other element 30px, either 0 while hidden, with no gap.
const cardWidths = {};
const boxWidth = (n) => { if (n.nodeType !== 1 || n.hidden) return 0; if ("layoutWidth" in n) return n.layoutWidth;
  if (n.classList.contains("card-tags")) return cardWidths[n.closest("[data-video-key]")?.attrs["data-video-key"]] ?? 0;
  return n.classList.contains("tag-chip") ? 50 : 30; };
const contentWidth = (n) => n.childNodes.reduce((sum, c) => sum + boxWidth(c), 0);
const resizeObservers = [];
globalThis.ResizeObserver = class { constructor(callback) { this.callback = callback; this.reported = new Map(); resizeObservers.push(this); }
  observe(target) { if (!this.reported.has(target)) this.reported.set(target, -1); } unobserve(target) { this.reported.delete(target); } disconnect() { this.reported.clear(); } };
const deliverResize = () => { for (const ro of resizeObservers) { const entries = [];
  for (const [target, last] of ro.reported) { const width = target.clientWidth; if (width === last) continue; ro.reported.set(target, width);
    entries.push({ target, contentRect: { x: 0, y: 0, top: 0, left: 0, width, height: 20, right: width, bottom: 20 }, contentBoxSize: [{ inlineSize: width, blockSize: 20 }], borderBoxSize: [{ inlineSize: width, blockSize: 20 }] }); }
  if (entries.length) { try { ro.callback(entries, ro); } catch (e) { errors.push(String((e && e.stack) || e)); } } } };
let uid = 0;
const adopt = (parent, nodes) => { for (const n of nodes) { if (n.parentElement && n.parentElement !== parent) n.parentElement.childNodes.splice(n.parentElement.childNodes.indexOf(n), 1); n.parentElement = parent; } return nodes; };
const element = (tag) => {
  const el = { nodeType: 1, tagName: tag.toUpperCase(), localName: tag.toLowerCase(), uid: ++uid, attrs: {}, childNodes: [], parentElement: null, listeners: {}, style: {}, root: false,
    get children() { return el.childNodes.filter((n) => n.nodeType === 1); },
    get firstElementChild() { return el.children[0] ?? null; },
    get nextElementSibling() { const s = el.parentElement?.children ?? []; return s[s.indexOf(el) + 1] ?? null; },
    get previousElementSibling() { const s = el.parentElement?.children ?? []; return s[s.indexOf(el) - 1] ?? null; },
    get id() { return el.attrs.id ?? ""; }, set id(v) { el.attrs.id = String(v); },
    get className() { return el.attrs.class ?? ""; }, set className(v) { el.attrs.class = String(v); },
    get hidden() { return "hidden" in el.attrs; }, set hidden(v) { if (v) el.attrs.hidden = ""; else delete el.attrs.hidden; },
    get href() { return el.attrs.href ?? ""; }, set href(v) { el.attrs.href = String(v); },
    get textContent() { return el.childNodes.map((n) => n.textContent).join(""); },
    set textContent(v) { el.setChildren(v == null || v === "" ? [] : [textNode(v)]); },
    get innerHTML() { return el.childNodes.map(serialize).join(""); },
    set innerHTML(v) { el.setChildren(parse(String(v))); },
    get outerHTML() { return serialize(el); },
    set outerHTML(v) { const parent = el.parentElement; if (!parent) throw new Error("outerHTML set on a detached node");
      const nodes = parse(String(v)); parent.childNodes.splice(parent.childNodes.indexOf(el), 1, ...nodes); for (const n of nodes) n.parentElement = parent; el.parentElement = null; notify(parent, nodes, [el]); },
    get isConnected() { for (let n = el; n; n = n.parentElement) if (n.root) return true; return false; },
    get clientWidth() { return boxWidth(el); },
    get offsetWidth() { return boxWidth(el); },
    get scrollWidth() { return Math.max(boxWidth(el), contentWidth(el)); },
    getBoundingClientRect: () => { const inRow = el.parentElement?.classList.contains("card-tags"); const siblings = inRow ? el.parentElement.childNodes : [];
      const left = siblings.slice(0, siblings.indexOf(el)).reduce((sum, c) => sum + boxWidth(c), 0); const width = boxWidth(el);
      return { x: left, y: 0, top: 0, bottom: 20, left, right: left + width, width, height: 20 }; },
    setChildren: (nodes) => { const removed = el.childNodes; for (const n of removed) n.parentElement = null; el.childNodes = adopt(el, nodes); notify(el, nodes, removed); },
    classList: { add: (...c) => { const s = new Set(el.className.split(/\s+/).filter(Boolean)); c.forEach((x) => s.add(x)); el.className = [...s].join(" "); },
      remove: (...c) => { el.className = el.className.split(/\s+/).filter((x) => x && !c.includes(x)).join(" "); },
      contains: (c) => el.className.split(/\s+/).includes(c),
      toggle: (c, force) => { const on = force ?? !el.classList.contains(c); if (on) el.classList.add(c); else el.classList.remove(c); return on; } },
    append: (...items) => { const nodes = items.map((i) => (typeof i === "string" ? textNode(i) : i)); adopt(el, nodes); el.childNodes.push(...nodes); notify(el, nodes, []); },
    prepend: (...items) => { const nodes = items.map((i) => (typeof i === "string" ? textNode(i) : i)); adopt(el, nodes); el.childNodes.unshift(...nodes); notify(el, nodes, []); },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { el.setChildren(items.map((i) => (typeof i === "string" ? textNode(i) : i))); },
    remove: () => { const p = el.parentElement; if (p) { p.childNodes.splice(p.childNodes.indexOf(el), 1); el.parentElement = null; notify(p, [], [el]); } },
    insertAdjacentHTML: (position, markup) => { const nodes = parse(String(markup)); const where = String(position).toLowerCase();
      if (where === "beforeend" || where === "afterbegin") { adopt(el, nodes); if (where === "beforeend") el.childNodes.push(...nodes); else el.childNodes.unshift(...nodes); notify(el, nodes, []); return; }
      const p = el.parentElement; if (!p) throw new Error(`insertAdjacentHTML ${position} on a detached node`); adopt(p, nodes);
      p.childNodes.splice(p.childNodes.indexOf(el) + (where === "afterend" ? 1 : 0), 0, ...nodes); notify(p, nodes, []); },
    setAttribute: (n, v) => { el.attrs[String(n).toLowerCase()] = String(v); },
    removeAttribute: (n) => { delete el.attrs[String(n).toLowerCase()]; },
    hasAttribute: (n) => String(n).toLowerCase() in el.attrs, getAttribute: (n) => el.attrs[String(n).toLowerCase()] ?? null,
    toggleAttribute: (n, force) => { const on = force ?? !el.hasAttribute(n); if (on) el.setAttribute(n, ""); else el.removeAttribute(n); return on; },
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); }, removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    matches: (sel) => matches(el, sel), closest: (sel) => { for (let n = el; n; n = n.parentElement) if (matches(n, sel)) return n; return null; },
    querySelectorAll: (sel) => descendants(el).filter((n) => matches(n, sel)), querySelector: (sel) => el.querySelectorAll(sel)[0] ?? null,
  };
  el.dataset = new Proxy({}, { get: (_, k) => (typeof k === "string" ? el.attrs["data-" + kebab(k)] : undefined),
    set: (_, k, v) => { el.attrs["data-" + kebab(String(k))] = String(v); return true; }, deleteProperty: (_, k) => { delete el.attrs["data-" + kebab(String(k))]; return true; } });
  return Object.setPrototypeOf(el, HTMLElement.prototype);
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
const byId = new Map();
const rootEl = (id) => { if (!byId.has(id)) { const el = element("div"); el.root = true; el.attrs.id = id; byId.set(id, el); } return byId.get(id); };
globalThis.document = { body: element("body"), getElementById: rootEl, createElement: (t) => element(t), createTextNode: (v) => textNode(v), querySelector: () => null, querySelectorAll: () => [], addEventListener() {} };
process.on("unhandledRejection", (r) => { errors.push(String((r && r.stack) || r)); });
// A browser lays out and delivers resize observations after each task; here every settle step does so.
const settle = async () => { for (let i = 0; i < 5; i += 1) { await new Promise((resolve) => setTimeout(resolve, 5)); deliverResize(); } };

// The stubs checked on a hand-built row with observers of the runner's own, so a row the module leaves unfitted is not a dead stub.
const bench = rootEl("bench");
const benchAdded = [];
const benchWidths = [];
new MutationObserver((records) => records.forEach((r) => r.addedNodes.forEach((n) => { if (n.nodeType === 1) benchAdded.push(n.className); }))).observe(bench, { childList: true, subtree: true });
bench.innerHTML = '<div class="card-tags"><a class="tag-chip">x</a><a class="tag-chip">y</a><span>m</span></div>';
const benchRow = bench.firstElementChild;
benchRow.layoutWidth = 120;
const benchResizer = new ResizeObserver((entries) => entries.forEach((e) => benchWidths.push(e.contentRect.width)));
benchResizer.observe(benchRow);
await settle();
const benchScroll = [benchRow.scrollWidth];
benchRow.querySelectorAll(".tag-chip")[1].hidden = true;
benchScroll.push(benchRow.scrollWidth);
benchRow.insertAdjacentHTML("beforeend", '<a class="tag-chip">z</a>');
benchRow.layoutWidth = 200;
await settle();
benchResizer.disconnect();
const benchReport = { element: benchRow instanceof HTMLElement, scroll: benchScroll, added: benchAdded, widths: benchWidths };

const m = await import(process.env.BUNDLE);
const container = rootEl("video-cards");
let observeError = null;
if (typeof m.observeTagRows !== "function") observeError = "observeTagRows is not exported";
else { try { m.observeTagRows(container); } catch (e) { observeError = String((e && e.stack) || e); } }
const cards = JSON.parse(process.env.CARDS);
for (const card of cards) cardWidths[card.key] = card.width;
const snapshot = () => Object.fromEntries(container.querySelectorAll("[data-video-key]").map((card) => {
  const row = card.querySelector(".card-tags");
  if (!row) return [card.attrs["data-video-key"], null];
  const chips = row.children.filter((n) => n.classList.contains("tag-chip"));
  const others = row.children.filter((n) => !n.classList.contains("tag-chip"));
  return [card.attrs["data-video-key"], { chips: chips.map((c) => c.textContent), visible: chips.filter((c) => !c.hidden).map((c) => c.textContent),
    markers: others.map((o) => ({ hidden: o.hidden, text: o.textContent.trim(), label: o.getAttribute("aria-label") })), width: row.clientWidth, scroll: row.scrollWidth }];
}));
// The first card arrives by innerHTML and the rest by insertAdjacentHTML, as the feed renders a page and then appends the next.
const [first, ...later] = cards;
container.innerHTML = m.renderVideoCard(first.row);
await settle();
for (const card of later) container.insertAdjacentHTML("beforeend", m.renderVideoCard(card.row));
await settle();
const snapshots = [snapshot()];
for (const step of JSON.parse(process.env.RESIZES)) { cardWidths[step.key] = step.width; await settle(); snapshots.push(snapshot()); }
process.stdout.write(JSON.stringify({ bench: benchReport, observeError, errors, cards: container.querySelectorAll("[data-video-key]").length, snapshots }) + "\n", () => process.exit(0));
"""

# The video page runner of tests/active/test_frontend_video_page.py (RUNNER), cut to the taxonomy: a recording `document`, `window.location` with a `?api=` the production build must not carry into a link, the storages, `ResizeObserver` and `getComputedStyle`, and a `fetch` answering `/api/video` with the case's body and `{}` elsewhere. It reports each child of `#video-tags`.
VIDEO_PAGE_RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: process.env.SEARCH },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage, addEventListener() {} };
const text = (value) => ({ nodeType: 3, textContent: String(value) });
const nodes = (items) => items.map((n) => (typeof n === "string" ? text(n) : n));
const element = (tag, hidden = false) => {
  const classes = new Set();
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), hidden, disabled: false, children: [], dataset: {}, style: {}, attrs: {}, listeners: {}, parentElement: null,
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? "").join(""); },
    set innerHTML(v) { el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    get href() { return el.attrs.href ?? ""; },
    set href(v) { el.attrs.href = String(v); },
    classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c), toggle: (c, force) => { const on = force ?? !classes.has(c); if (on) classes.add(c); else classes.delete(c); return on; } },
    append: (...items) => { el.children.push(...nodes(items)); },
    appendChild: (child) => { el.children.push(child); return child; },
    replaceChildren: (...items) => { el.children = nodes(items); },
    setAttribute: (name, value) => { if (name === "hidden") el.hidden = true; else if (name === "disabled") el.disabled = true; else if (name === "class") el.className = value; else el.attrs[name] = String(value); },
    removeAttribute: (name) => { if (name === "hidden") el.hidden = false; else if (name === "disabled") el.disabled = false; else delete el.attrs[name]; },
    toggleAttribute: (name, force) => { const on = force ?? !(name === "hidden" ? el.hidden : name === "disabled" ? el.disabled : name in el.attrs); el[on ? "setAttribute" : "removeAttribute"](name, ""); return on; },
    getAttribute: (name) => (name === "hidden" ? (el.hidden ? "" : null) : name === "disabled" ? (el.disabled ? "" : null) : el.attrs[name] ?? null),
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener: (type, listener) => { (el.listeners[type] ??= []).push(listener); },
    removeEventListener: (type, listener) => { el.listeners[type] = (el.listeners[type] ?? []).filter((l) => l !== listener); },
    insertAdjacentHTML() {}, remove() {},
  };
  return el;
};
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div")); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
const requested = [];
globalThis.fetch = async (input) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requested.push(url.pathname);
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/video") return new Response(process.env.VIDEO_BODY, { status: 200, headers });
  return new Response("{}", { status: 200, headers });
};
const rejections = [];
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
await import(process.env.BUNDLE);
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
await settle();
const tags = (byId.get("video-tags")?.children ?? []).map((c) => ({ type: c.nodeType, tag: c.tagName ?? null, cls: c.className ?? null, text: c.textContent, href: c.attrs?.href ?? null }));
process.stdout.write(JSON.stringify({ requested, title: byId.get("video-title")?.textContent ?? null, tags, rejections }) + "\\n", () => process.exit(0));
"""

# The similars runner of tests/active/test_frontend_video_page_similars.py (RUNNER), with the case's `?api=` in `window.location` and no intersections: it reports the markup `#similar-videos` holds once the first batch has rendered.
SIMILARS_RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
// The document is far taller than the window and nothing has scrolled, so a fill-viewport pass never asks for another batch.
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: process.env.SEARCH },
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
const getElementById = (id) => { if (!byId.has(id)) { const el = element("div"); el.id = id; byId.set(id, el); } return byId.get(id); };
globalThis.document = {
  title: "", body: element("body"), documentElement: { scrollHeight: 10000, clientHeight: 800 },
  getElementById, createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: (selector) => (/^#[\\w-]+$/.test(selector) ? getElementById(selector.slice(1)) : null), querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
const requests = [];
const answer = process.env.RECOMMENDATIONS_BODY;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push(url.pathname);
  return new Response(url.pathname === "/recommendations" ? answer : "{}", { status: 200, headers: { "content-type": "application/json" } });
};
const rejections = [];
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
await import(process.env.BUNDLE);
for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
process.stdout.write(JSON.stringify({ requests, similar: getElementById("similar-videos").innerHTML, rejections }) + "\\n", () => process.exit(0));
"""

# The fit runner up to its import of the card module (its recording DOM, observers, layout and stub check), then a page: the page module runs on that DOM with `window`, the storages, `IntersectionObserver`, `getComputedStyle` and a `fetch` answering ROWS_PATH once with ROWS_BODY and `{}` otherwise. The sentinels sit far below the viewport, so no page asks for a second batch. It reports each keyed card of the CONTAINER the page renders into, as the fit runner does, after the page settles and after each resize.
PAGE_FIT_RUNNER = FIT_RUNNER[:FIT_RUNNER.index("const m = await import(process.env.BUNDLE);")] + r"""
const env = process.env;
const memory = () => { const s = new Map(); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: env.BASE, pathname: env.PATHNAME, search: env.SEARCH }, localStorage, sessionStorage, innerHeight: 800, scrollY: 0,
  addEventListener() {}, removeEventListener() {}, confirm: () => true, history: { pushState() {}, replaceState() {} } };
Object.assign(document, { title: "", documentElement: { scrollHeight: 100000, clientHeight: 800 } });
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
for (const id of ["feed-sentinel", "search-sentinel", "similar-sentinel"]) rootEl(id).getBoundingClientRect = () => ({ x: 0, y: 100000, top: 100000, bottom: 100000, left: 0, right: 0, width: 0, height: 0 });
Object.assign(cardWidths, JSON.parse(env.WIDTHS));
const requested = [];
let answered = false;
globalThis.fetch = async (input) => { const url = new URL(String(input?.url ?? input), env.BASE); requested.push(url.pathname);
  const rows = url.pathname === env.ROWS_PATH && !answered; if (rows) answered = true;
  return new Response(rows ? env.ROWS_BODY : "{}", { status: 200, headers: { "content-type": "application/json" } }); };
await import(env.BUNDLE);
for (let i = 0; i < 8; i += 1) await settle();
const container = rootEl(env.CONTAINER);
const snapshot = () => Object.fromEntries(container.querySelectorAll("[data-video-key]").map((card) => {
  const row = card.querySelector(".card-tags");
  if (!row) return [card.attrs["data-video-key"], null];
  const chips = row.children.filter((n) => n.classList.contains("tag-chip"));
  const others = row.children.filter((n) => !n.classList.contains("tag-chip"));
  return [card.attrs["data-video-key"], { chips: chips.map((c) => c.textContent), visible: chips.filter((c) => !c.hidden).map((c) => c.textContent),
    markers: others.map((o) => ({ hidden: o.hidden, text: o.textContent.trim(), label: o.getAttribute("aria-label") })), width: row.clientWidth, scroll: row.scrollWidth }];
}));
const snapshots = [snapshot()];
for (const step of JSON.parse(env.RESIZES)) { cardWidths[step.key] = step.width; await settle(); snapshots.push(snapshot()); }
process.stdout.write(JSON.stringify({ bench: benchReport, requested, errors, snapshots }) + "\n", () => process.exit(0));
"""

FIVE = "tags.example::five"
FITS = "tags.example::fits"
LATE = "tags.example::late"
# Five 50px chips and a 30px marker: at 160 two chips and the marker fit (130) where three chips alone would too (150), so only a fit that counts the marker shows two. The last two cards are appended; unfitted, the late five-chip row shows all five and overflows (250).
CARD_ROWS_FIT = [
    {"key": FIVE, "width": 160, "row": {"video_uuid": "five", "instance_domain": "tags.example", "title": "Five tags", "tags": ["t1", "t2", "t3", "t4", "t5"]}},
    {"key": FITS, "width": 160, "row": {"video_uuid": "fits", "instance_domain": "tags.example", "title": "Two tags", "tags": ["solo", "duo"]}},
    {"key": LATE, "width": 160, "row": {"video_uuid": "late", "instance_domain": "tags.example", "title": "Late five tags", "tags": ["t1", "t2", "t3", "t4", "t5"]}},
]
# 210 holds three chips and the marker (180) but not four (230); 300 holds all five without it (250); 160 again goes back to two. Then the exact fits: 130 is two chips and the marker, 180 three and the marker, 250 all five alone; 70 holds the marker and no chip (80).
RESIZES = [{"key": FIVE, "width": 210}, {"key": FIVE, "width": 300}, {"key": FIVE, "width": 160},
           {"key": FIVE, "width": 130}, {"key": FIVE, "width": 180}, {"key": FIVE, "width": 250}, {"key": FIVE, "width": 70}]

# One five-chip row as each page's endpoint returns it; views and likes keep the feed from fetching live stats.
PAGE_ROW = {"video_id": "five", "video_uuid": "five", "instance_domain": "tags.example", "title": "Five tags", "tags": ["t1", "t2", "t3", "t4", "t5"], "views": 1, "likes": 1}
# Each page's bundle, URL, card container and the endpoint its cards come from.
PAGES = {
    "feed": {"bundle": "feed.mjs", "PATHNAME": "/", "SEARCH": "", "CONTAINER": "video-cards", "ROWS_PATH": "/recommendations", "ROWS_BODY": {"rows": [PAGE_ROW]}},
    "search": {"bundle": "search.mjs", "PATHNAME": "/search.html", "SEARCH": "?q=x", "CONTAINER": "search-results", "ROWS_PATH": "/api/v1/search/videos", "ROWS_BODY": {"rows": [PAGE_ROW], "total": 1}},
    "up-next": {"bundle": "page.mjs", "PATHNAME": "/video-page.html", "SEARCH": "?id=v1&host=peer.example", "CONTAINER": "similar-videos", "ROWS_PATH": "/recommendations", "ROWS_BODY": {"rows": [PAGE_ROW], "seed": {"mode": "upnext"}}},
}
PAGE_RESIZES = [{"key": FIVE, "width": 300}]


def _build(out: Path, name: str, *, dev: bool, entry: Path = FRONTEND / "src" / "components" / "video-card.ts") -> Path:
    target = out / name
    subprocess.run([str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={target}",
                    f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", f"--define:import.meta.env.DEV={'true' if dev else 'false'}"],
                   check=True, capture_output=True)
    return target


def _node(runner: Path, env: dict[str, str]) -> dict:
    proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", ""), **env})
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.splitlines()[-1])


class _Tree(HTMLParser):
    """Markup as nested dicts, nesting exactly as written: an `<a>` opened inside another stays inside it, where a browser would close the outer one, so a chip written into a video link reads as inside it."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self, markup: str):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": None, "attrs": {}, "children": [], "parent": None}
        self._stack = [self.root]
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: v or "" for k, v in attrs}, "children": [], "parent": self._stack[-1]}
        self._stack[-1]["children"].append(node)
        if tag not in self.VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1]["children"].append({"tag": tag, "attrs": {k: v or "" for k, v in attrs}, "children": [], "parent": self._stack[-1]})

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i]["tag"] == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        self._stack[-1]["children"].append(data)


def _elements(node: dict) -> list[dict]:
    return [n for child in node["children"] if isinstance(child, dict) for n in (child, *_elements(child))]


def _classes(node: dict) -> list[str]:
    return node["attrs"].get("class", "").split()


def _text(node: dict) -> str:
    return "".join(child if isinstance(child, str) else _text(child) for child in node["children"])


def _ancestors(node: dict) -> list[dict]:
    found = []
    while node["parent"] is not None and node["parent"]["tag"] is not None:
        node = node["parent"]
        found.append(node)
    return found


def _chips(node: dict) -> list[dict]:
    return [n for n in _elements(node) if "tag-chip" in _classes(n)]


def _query(href: str | None) -> tuple[str, dict]:
    """A link's path and its query parsed independently of the module, so a check reads what a browser would send."""
    parts = urlsplit(href or "")
    return parts.path, parse_qs(parts.query, keep_blank_values=True)


@pytest.fixture(scope="module")
def bundles(tmp_path_factory) -> Path:
    """`video-card.ts` built for production (`card_prod.mjs`) and for dev (`card_dev.mjs`), the video, feed and search pages built for production (`page.mjs`, `feed.mjs`, `search.mjs`), and the runners beside them."""
    out = tmp_path_factory.mktemp("tag_chips")
    _build(out, "card_prod.mjs", dev=False)
    _build(out, "card_dev.mjs", dev=True)
    _build(out, "page.mjs", dev=False, entry=FRONTEND / "src" / "pages" / "video-page" / "index.ts")
    _build(out, "feed.mjs", dev=False, entry=FRONTEND / "src" / "pages" / "videos" / "index.ts")
    _build(out, "search.mjs", dev=False, entry=FRONTEND / "src" / "pages" / "search" / "index.ts")
    for name, runner in [("call.mjs", CALL_RUNNER), ("fit.mjs", FIT_RUNNER), ("video.mjs", VIDEO_PAGE_RUNNER), ("similars.mjs", SIMILARS_RUNNER), ("page_fit.mjs", PAGE_FIT_RUNNER)]:
        (out / name).write_text(runner)
    return out


def _calls(bundles: Path, calls: list[list], *, dev: bool = False) -> list[dict]:
    """Each `[export, *args]` called on the card module: `{"value": ...}`, `{"undefined": true}` or `{"error": ...}`, in order."""
    results = _node(bundles / "call.mjs", {"BUNDLE": str(bundles / ("card_dev.mjs" if dev else "card_prod.mjs")), "CALLS": json.dumps(calls)})
    assert len(results) == len(calls), results
    return results


def _markup(result: dict) -> _Tree:
    return _Tree(result.get("value") if isinstance(result.get("value"), str) else "")


SEARCH_WITH_API = "?id=v1&host=peer.example&api=http%3A%2F%2Fapi.example"
SMILE = "\U0001F600"


def test_tag_search_url_encodes_the_tag_for_the_search_page_and_carries_api_only_from_a_dev_build(bundles):
    prod = _calls(bundles, [["tagSearchUrl", "a b&c"], ["tagSearchUrl", "a b&c", API]])
    dev = _calls(bundles, [["tagSearchUrl", "a b&c", API], ["tagSearchUrl", "a b&c"]], dev=True)

    # a raw concatenation reads "tag=a b&c", which splits the tag at "&"; encodeURIComponent reads "a%20b%26c"
    assert prod[0] == {"value": "/search.html?tag=a+b%26c"}, prod  # C1
    # a production link carrying ?api= would repoint the next page's API at whatever the URL named
    assert prod[1] == {"value": "/search.html?tag=a+b%26c"}, prod  # C1
    # a URL that never carries api reads no "api" key here
    assert _query(dev[0].get("value")) == ("/search.html", {"tag": ["a b&c"], "api": [API]}), dev  # C1
    # with no apiParam a dev link has no api, not "api=null" or "api=undefined"
    assert dev[1] == {"value": "/search.html?tag=a+b%26c"}, dev  # C1


def test_tag_search_url_is_null_for_a_blank_tag_and_past_64_code_points_and_a_link_at_64(bundles):
    results = _calls(bundles, [["tagSearchUrl", "a" * 64], ["tagSearchUrl", SMILE * 64], ["tagSearchUrl", ""], ["tagSearchUrl", "   "], ["tagSearchUrl", "a" * 65], ["tagSearchUrl", SMILE * 65]])
    at_max, astral_at_max, empty, blank, past_max, astral_past_max = results

    assert _query(at_max.get("value")) == ("/search.html", {"tag": ["a" * 64]}), at_max  # C1
    # 64 code points are 128 UTF-16 units, so a limit read off String.length refuses the tag the Engine accepts
    assert _query(astral_at_max.get("value")) == ("/search.html", {"tag": [SMILE * 64]}), astral_at_max  # C1
    # a blank tag is a 400 at the Engine, so it gets no link rather than "?tag=" or "?tag=+++"
    assert (empty, blank) == ({"value": None}, {"value": None}), (empty, blank)  # C1
    # one past the Engine's SEARCH_MAX_TAG_LENGTH is a 400 too
    assert (past_max, astral_past_max) == ({"value": None}, {"value": None}), (past_max, astral_past_max)  # C1


def test_render_tag_chips_returns_empty_for_no_tags_and_for_a_blank_only_list_and_a_chip_for_one_tag(bundles):
    one, absent, null, empty, blank_only = _calls(bundles, [["renderTagChips", ["solo"]], ["renderTagChips"], ["renderTagChips", None], ["renderTagChips", []], ["renderTagChips", ["", "   "]]])

    # the positive half: a function returning "" for everything passes the four absences below
    assert [_text(chip) for chip in _chips(_markup(one).root)] == ["solo"], one  # C1
    # a row holding only the marker, or a throw on a row cached before tags existed, gives a card an empty tag line
    assert [absent, null, empty, blank_only] == [{"value": ""}] * 4, [absent, null, empty, blank_only]  # C1


def test_render_tag_chips_links_each_searchable_tag_in_the_uploaders_order_drops_unsearchable_ones_and_ends_with_a_hidden_marker(bundles):
    tags = ["zeta", "Lo-fi & Chill", "   ", "a" * 65, "alpha", SMILE * 64]
    kept = ["zeta", "Lo-fi & Chill", "alpha", SMILE * 64]
    prod = _calls(bundles, [["renderTagChips", tags], *(["tagSearchUrl", tag] for tag in kept)])
    dev = _calls(bundles, [["renderTagChips", tags, API], *(["tagSearchUrl", tag, API] for tag in kept)], dev=True)
    chips = _chips(_markup(prod[0]).root)
    dev_chips = _chips(_markup(dev[0]).root)

    # sorted chips put "Lo-fi & Chill" and "alpha" first; keeping every tag adds the blank and the 65-character one; a String.length limit drops the emoji
    assert [_text(chip) for chip in chips] == kept, prod[0]  # C1
    assert [chip["tag"] for chip in chips] == ["a"] * 4, prod[0]  # C1
    # read by an independent parser, each link searches its own tag and carries nothing else
    assert [_query(chip["attrs"].get("href")) for chip in chips] == [("/search.html", {"tag": [tag]}) for tag in kept], prod[0]  # C1
    assert [chip["attrs"].get("href") for chip in chips] == [result.get("value") for result in prod[1:]], prod  # C1
    # a row that ignores apiParam loses the dev build's API override on every chip
    assert [chip["attrs"].get("href") for chip in dev_chips] == [result.get("value") for result in dev[1:]], dev  # C1
    assert [_query(chip["attrs"].get("href")) for chip in dev_chips] == [("/search.html", {"tag": [tag], "api": [API]}) for tag in kept], dev[0]  # C1
    row = chips[0]["parent"]
    assert "card-tags" in _classes(row) and all(chip["parent"] is row for chip in chips), prod[0]  # C1
    # the marker is the row's one other element, present before any fit and hidden until one counts what it hides
    markers = [n for n in row["children"] if isinstance(n, dict) and all(n is not chip for chip in chips)]
    assert [("hidden" in marker["attrs"]) for marker in markers] == [True], prod[0]  # C1
    # the marker ends the row, after every chip, so the chips the fit hides from the end are the ones it stands beside
    assert ["chip" if any(n is chip for chip in chips) else "marker" for n in row["children"] if isinstance(n, dict)] == ["chip"] * 4 + ["marker"], prod[0]  # C1


def test_render_tag_chips_shows_a_script_tag_and_a_quote_as_text_and_writes_no_style_attribute(bundles):
    tags = ["<script>alert(1)</script>", 'x" onmouseover="alert(2)', "plain"]
    result = _calls(bundles, [["renderTagChips", tags]])[0]
    tree = _markup(result)
    chips = _chips(tree.root)

    # unescaped, the first tag becomes a script element with no chip text and the second breaks out of its attribute
    assert [_text(chip) for chip in chips] == tags, result  # C1
    assert [_query(chip["attrs"].get("href"))[1].get("tag") for chip in chips] == [[tag] for tag in tags], result  # C1
    assert [n["tag"] for n in _elements(tree.root) if n["tag"] == "script" or "onmouseover" in n["attrs"]] == [], result  # C1
    # the page's CSP allows no inline style, so the fit hides chips with the hidden attribute alone
    assert [n["tag"] for n in _elements(tree.root) if "style" in n["attrs"]] == [] and "style=" not in result.get("value", ""), result  # C1


def test_a_feed_card_puts_its_tag_row_after_the_video_link_with_no_chip_inside_any_link(bundles):
    row = {"video_uuid": "card", "instance_domain": "tube.example", "title": "Card with tags", "tags": ["one", "two & three"]}
    result = _calls(bundles, [["renderVideoCard", row, {"actions": True, "apiParam": API}]])[0]
    tree = _markup(result)
    links = [n for n in _elements(tree.root) if n["tag"] == "a" and "video-link" in _classes(n)]
    chips = _chips(tree.root)

    # control: the card rendered the row, so the readings below come from real card markup
    assert len(links) == 1 and "Card with tags" in _text(links[0]), result
    assert [_text(chip) for chip in chips] == ["one", "two & three"], result  # C1
    # a row written inside the video link puts both chips under a.video-link
    assert [[a["attrs"].get("class") for a in _ancestors(chip) if a["tag"] == "a"] for chip in chips] == [[], []], result  # C1
    # the production feed links each chip to its search without the ?api= the card was given
    assert [(chip["tag"], _query(chip["attrs"].get("href"))) for chip in chips] == [("a", ("/search.html", {"tag": ["one"]})), ("a", ("/search.html", {"tag": ["two & three"]}))], result  # C1
    tag_row = chips[0]["parent"]
    card = links[0]["parent"]
    order = [n is tag_row and "row" or n is links[0] and "link" or n["tag"] for n in card["children"] if isinstance(n, dict)]
    assert "card-tags" in _classes(tag_row) and "row" in order and order.index("row") > order.index("link"), (order, result)  # C1


def test_up_next_cards_are_keyed_divs_holding_the_video_link_then_a_row_of_tag_search_links_without_the_pages_api(bundles):
    rows = [{"video_id": "v0", "instance_domain": "videos.example", "title": "First", "tags": ["lo-fi & chill", "beats"]},
            {"video_id": "v1", "instance_domain": "videos.example", "title": "Second", "tags": ["   ", "study"]}]
    page = _node(bundles / "similars.mjs", {"BASE": BASE, "BUNDLE": str(bundles / "page.mjs"), "SEARCH": SEARCH_WITH_API,
                                             "RECOMMENDATIONS_BODY": json.dumps({"rows": rows, "seed": {"mode": "upnext"}})})
    tree = _Tree(page["similar"])
    cards = [n for n in _elements(tree.root) if "data-video-key" in n["attrs"]]

    # control: the page asked for its up-next rows and rendered one keyed card per row, in order
    assert "/recommendations" in page["requests"], page["requests"]
    assert [card["attrs"]["data-video-key"] for card in cards] == ["videos.example::v0", "videos.example::v1"], page["similar"][:600]
    # today the keyed card is itself the video link, so any chip in it would sit inside a link
    assert [(card["tag"], "similar-card-item" in _classes(card)) for card in cards] == [("div", True), ("div", True)], page["similar"][:600]  # C1
    layout = []
    for card in cards:
        children = [n for n in card["children"] if isinstance(n, dict)]
        layout.append([(n["tag"], "similar-card-link" in _classes(n), "card-tags" in _classes(n)) for n in children])
    # the link first, the tag row after it as its sibling
    assert layout == [[("a", True, False), ("div", False, True)]] * 2, (layout, page["similar"][:600])  # C1
    chips = [_chips(card) for card in cards]
    assert [[_text(chip) for chip in card] for card in chips] == [["lo-fi & chill", "beats"], ["study"]], page["similar"][:600]  # C1
    assert [[a["attrs"].get("class") for chip in card for a in _ancestors(chip) if a["tag"] == "a"] for card in chips] == [[], []], page["similar"][:600]  # C1
    # the page's ?api= reaches no link from a production build
    assert [[(chip["tag"], _query(chip["attrs"].get("href"))) for chip in card] for card in chips] == [
        [("a", ("/search.html", {"tag": ["lo-fi & chill"]})), ("a", ("/search.html", {"tag": ["beats"]}))], [("a", ("/search.html", {"tag": ["study"]}))]], page["similar"][:600]  # C1


def test_the_video_page_links_each_searchable_tag_to_its_search_without_api_and_keeps_a_blank_or_overlong_tag_a_plain_chip(bundles):
    tags = ["alpha", "a b&c", "   ", SMILE * 65]
    page = _node(bundles / "video.mjs", {"BASE": BASE, "BUNDLE": str(bundles / "page.mjs"), "SEARCH": SEARCH_WITH_API,
                                          "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": "Tag fixture", "tags": tags})})
    shown = page["tags"]

    # control: the page read /api/video and shows one tag-chip per stored tag, in order
    assert "/api/video" in page["requested"] and page["title"] == "Tag fixture", page
    assert [(chip["text"], "tag-chip" in (chip["cls"] or "").split()) for chip in shown] == [(tag, True) for tag in tags], shown
    # today every chip is a span with no href; the production build carries no ?api= though the page's URL has one
    assert [(chip["tag"], chip["href"]) for chip in shown[:2]] == [("A", "/search.html?tag=alpha"), ("A", "/search.html?tag=a+b%26c")], shown  # C1
    # a tag the search would refuse stays a chip of text, not a link to a 400 or to "?tag="
    assert [(chip["tag"], chip["href"]) for chip in shown[2:]] == [("SPAN", None), ("SPAN", None)], shown  # C1


def _fit(bundles: Path) -> dict:
    report = _node(bundles / "fit.mjs", {"BUNDLE": str(bundles / "card_prod.mjs"), "CARDS": json.dumps(CARD_ROWS_FIT), "RESIZES": json.dumps(RESIZES)})
    # control: the stubs are live (a parsed row is an HTMLElement, its scrollWidth drops when a chip hides, a MutationObserver sees added rows and chips, a ResizeObserver reports the first width and a change), and both cards rendered
    assert report["bench"] == {"element": True, "scroll": [130, 120], "added": ["card-tags", "tag-chip"], "widths": [120, 200]}, report["bench"]
    assert report["cards"] == 3 and len(report["snapshots"]) == len(RESIZES) + 1, report
    return report


def _page_fit(bundles: Path, page: str) -> dict:
    config = PAGES[page]
    return _node(bundles / "page_fit.mjs", {"BASE": BASE, "BUNDLE": str(bundles / config["bundle"]), "PATHNAME": config["PATHNAME"], "SEARCH": config["SEARCH"], "CONTAINER": config["CONTAINER"],
                                            "ROWS_PATH": config["ROWS_PATH"], "ROWS_BODY": json.dumps(config["ROWS_BODY"]), "WIDTHS": json.dumps({FIVE: 160}), "RESIZES": json.dumps(PAGE_RESIZES)})


def test_a_five_chip_row_with_room_for_two_shows_two_chips_and_plus_3_and_refits_when_its_card_widens_and_narrows(bundles):
    report = _fit(bundles)
    narrow, wider, widest, narrowed = (snapshot[FIVE] or {} for snapshot in report["snapshots"][:4])
    why = (report["observeError"], report["errors"])

    # hiding until three chips alone fit, then adding the marker, leaves three chips and +2 overflowing at 180; hiding from the start shows t4 and t5
    assert narrow.get("visible") == ["t1", "t2"], (why, narrow)  # C2
    assert narrow.get("markers") == [{"hidden": False, "text": "+3", "label": "3 more tags"}], (why, narrow)  # C2
    # hidden, not removed, and what is left fits the row
    assert narrow.get("chips") == ["t1", "t2", "t3", "t4", "t5"] and narrow.get("scroll", 1) <= narrow.get("width", 0), (why, narrow)  # C2
    # a fit that never re-runs, or re-runs without showing the chips again, stays at two
    assert (wider.get("visible"), wider.get("markers")) == (["t1", "t2", "t3"], [{"hidden": False, "text": "+2", "label": "2 more tags"}]), (why, wider)  # C2
    assert (widest.get("visible"), [marker["hidden"] for marker in widest.get("markers", [])]) == (["t1", "t2", "t3", "t4", "t5"], [True]), (why, widest)  # C2
    # a fit that only ever shows more chips keeps all five at 160
    assert (narrowed.get("visible"), narrowed.get("markers")) == (["t1", "t2"], [{"hidden": False, "text": "+3", "label": "3 more tags"}]), (why, narrowed)  # C2


def test_an_appended_overflowing_row_is_fitted_and_a_row_whose_chips_all_fit_shows_them_all_and_keeps_its_marker_hidden_beside_one_that_overflows(bundles):
    report = _fit(bundles)
    overflowing, fitting, late = (report["snapshots"][0][key] or {} for key in (FIVE, FITS, LATE))
    why = (report["observeError"], report["errors"])

    # the positive half: the same fit, on the same page, shows the marker where chips do not fit
    assert [marker["hidden"] for marker in overflowing.get("markers", [])] == [False], (why, overflowing)  # C2
    # a fit that reaches only the rows of the first render leaves this appended row at all five chips, overflowing at 250, with its marker hidden
    assert (late.get("visible"), late.get("markers")) == (["t1", "t2"], [{"hidden": False, "text": "+3", "label": "3 more tags"}]), (why, late)  # C2
    # a fit that always hides at least one chip, or always shows the marker, reads otherwise here
    assert fitting.get("visible") == ["solo", "duo"], (why, fitting)  # C2
    assert [marker["hidden"] for marker in fitting.get("markers", [])] == [True], (why, fitting)  # C2


def test_a_row_exactly_as_wide_as_its_shown_chips_and_marker_keeps_them_and_one_too_narrow_for_any_chip_shows_plus_5(bundles):
    report = _fit(bundles)
    two, three, five, none = (snapshot[FIVE] or {} for snapshot in report["snapshots"][4:])
    why = (report["observeError"], report["errors"])

    # a fit that counts an exact fit as overflow shows one chip and +4 at 130, two and +3 at 180, four and +1 at 250
    assert (two.get("visible"), two.get("markers")) == (["t1", "t2"], [{"hidden": False, "text": "+3", "label": "3 more tags"}]), (why, two)  # C2
    assert (three.get("visible"), three.get("markers")) == (["t1", "t2", "t3"], [{"hidden": False, "text": "+2", "label": "2 more tags"}]), (why, three)  # C2
    assert (five.get("visible"), [marker["hidden"] for marker in five.get("markers", [])]) == (["t1", "t2", "t3", "t4", "t5"], [True]), (why, five)  # C2
    # a fit that always keeps one chip shows t1 and +4, overflowing at 80
    assert (none.get("visible"), none.get("markers")) == ([], [{"hidden": False, "text": "+5", "label": "5 more tags"}]), (why, none)  # C2


@pytest.mark.parametrize("page", PAGES)
def test_each_page_fits_the_tag_row_of_a_card_it_renders_and_refits_it_when_the_card_widens(bundles, page):
    report = _page_fit(bundles, page)
    rendered, widened = (snapshot.get(FIVE) or {} for snapshot in report["snapshots"])

    # control: the stubs are live and the page asked for its rows and rendered the five-tag card, keyed, in its card container
    assert report["bench"] == {"element": True, "scroll": [130, 120], "added": ["card-tags", "tag-chip"], "widths": [120, 200]}, report["bench"]
    assert PAGES[page]["ROWS_PATH"] in report["requested"] and [list(snapshot) for snapshot in report["snapshots"]] == [[FIVE], [FIVE]], report
    # a page that never calls observeTagRows on this container leaves the row unfitted: all five chips, the marker hidden, overflowing at 250
    assert (rendered.get("visible"), rendered.get("markers")) == (["t1", "t2"], [{"hidden": False, "text": "+3", "label": "3 more tags"}]), (report["errors"], rendered)  # C2
    # the page's rows reach the ResizeObserver, so the card's new width re-fits its row
    assert (widened.get("visible"), [marker["hidden"] for marker in widened.get("markers", [])]) == (["t1", "t2", "t3", "t4", "t5"], [True]), (report["errors"], widened)  # C2
