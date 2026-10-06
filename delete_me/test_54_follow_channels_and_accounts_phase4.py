"""The Following feed's cursor pager, `follows.ts` against the real Client, and the follow controls on the home cards, the video page and the channels page.

Cursor pager (`createCursorPager`, data/videos.ts), driven with a scripted `fetchPage`:
- Over a full page with a cursor, an empty page with a cursor, a short page with a cursor and a page with no cursor, `next()` resolves with the full page, then with the short page's row (asking twice in that one call, with each cursor in turn), then with the last page's row and `exhausted` set. `exhausted` is false until then, and once it is set a further `next()` resolves empty without fetching.
- An empty page whose cursor is null ends the walk: `exhausted` is set and nothing more is fetched.
- A fetch that throws rejects `next()` with its error and leaves the pager unexhausted, and the next call asks with the same cursor.
- On the home page, keyed and with `?mode=following`, the first feed request carries no cursor and gets an empty page with cursor `c1`. The page asks again with `c1`, gets two rows and no cursor, shows those two cards, and asks no more.

`follows.ts`, against the real Client and Engine (`engine_client`):
- `followVideoSource` for a search row's channel and its account, and `followChannel` for another row's channel key, each resolve with the stored follow keyed as whitelist.db keys it. `listFollows` returns exactly those three. `unfollow` of the channel resolves, and `listFollows` then returns the other two.
- With a never-issued key, and with no key, `listFollows`, `followVideoSource`, `followChannel` and `unfollow` each reject with `Profile key required`.

Follow controls. Each page module is bundled and run in node on a recording DOM that parses innerHTML, so delegated clicks, `closest` and `querySelector` work and a redraw replaces element objects. `fetch` is stubbed per case, and the page's feed or channel list is answered only after its follow list:
- Home, keyed, with a list of one channel on peer.example and one account. Both cards of that channel read "Unfollow channel", the card of that account reads "Unfollow account", and a card with the same channel_id on another host reads "Follow channel" / "Follow account". Unfollowing card 1's channel posts its key to `/api/profile/follows/remove` and relabels both cards of the channel. Following card 2's account posts `{kind, uuid, host}` to `/api/profile/follows` and relabels both cards of that account, but not the other host's card. A follow the Client refuses with a 400 leaves every label as it was and shows the error in that card's status. No card element is replaced over the toggles, and the list is fetched once.
- Home, keyless: every card reads "Follow channel" / "Follow account". A click on either shows "Following needs a profile. Create one from the Profile button." in that card's status and leaves the labels, and nothing is sent to `/api/profile/follows*`.
- Home, keyless, with `?mode=following`: no feed request and no cards, and that message is shown.
- Video page, keyed, with `/api/video` carrying `channelId` and `accountUrl` and a list holding the video's channel. It reads "Unfollow channel" and "Follow account" at load. Follow account posts the video form and flips to "Unfollow account". Block channel resets the channel button to "Follow channel" and leaves the account button as it is. Follow channel posts the video form and flips back. Unfollow account posts the account key to remove and flips to "Follow account".
- Video page, keyless: both buttons read "Follow …", a click on each shows "Following needs a profile. Create one from the Profile button on the home page.", and nothing is sent to the follow routes.
- Channels page, keyed, with a list holding c1 on tube.example. Its row reads "Unfollow"; c2 on tube.example and c1 on other.example read "Follow". Follow on c2 posts `{kind: "channel", instance_domain, channel_id}` and flips. Unfollow on c1 posts its key to remove and flips. A refused Follow keeps "Follow" and shows the error in its row. The list is fetched once.
- Channels page, keyless: every row reads "Follow". A click shows "Following needs a profile. Create one from the Profile button." in its row and sends nothing to the follow routes.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

# tests/active/conftest.py holds the Client and session Engine fixtures; a working-tree test sees them only by importing the chain `engine_client` and `dataset` depend on.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import dataset, engine, engine_client, identity_of, shared_trending_before, trending_seed  # noqa: E402,F401

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
KEY_STORAGE = {"profileKey:v1": "K" * 43}
NEEDS_PROFILE = "Following needs a profile. Create one from the Profile button."
NEEDS_PROFILE_VIDEO_PAGE = "Following needs a profile. Create one from the Profile button on the home page."
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

PAGER_RUNNER = r"""
const memory = () => { const s = new Map(); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: "http://client.test" }, localStorage, sessionStorage };
const m = await import(process.env.BUNDLE);
const script = JSON.parse(process.env.SCRIPT);
const asked = [];
const results = [];
const fetchPage = async (cursor) => {
  const step = script[asked.length];
  asked.push(cursor ?? null);
  if (!step) throw new Error(`fetch ${asked.length} was not scripted`);
  if (step.throw) throw new Error(step.throw);
  return step.page;
};
let pager = null;
for (let i = 0; i < Number(process.env.CALLS); i += 1) {
  try {
    // Built inside the loop so a module without createCursorPager answers every call with that error, which the assertions on each call then read.
    pager ??= m.createCursorPager(fetchPage);
    const payload = await pager.next();
    results.push({ rows: (payload.rows ?? []).map((r) => r.video_id), exhausted: pager.exhausted, asked: [...asked] });
  } catch (e) { results.push({ error: String(e?.message ?? e), exhausted: pager?.exhausted ?? null, asked: [...asked] }); }
}
process.stdout.write(JSON.stringify(results) + "\n", () => process.exit(0));
"""

FOLLOWS_RUNNER = r"""
const memory = () => { const s = new Map(); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
const m = await import(process.env.BUNDLE);
const base = process.env.BASE;
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");
const attempt = async (fn) => { try { const value = await fn(); return { ok: value ?? null }; } catch (e) { return { error: String(e?.message ?? e) }; } };
for (const [name, ...args] of JSON.parse(process.env.STEPS)) {
  if (name === "create") say({ key: await m.createProfile(base) });
  if (name === "store") { m.storeProfileKey(args[0]); say({ stored: true }); }
  if (name === "list") say(await attempt(() => m.listFollows(base)));
  if (name === "followVideo") say(await attempt(() => m.followVideoSource(base, ...args)));
  if (name === "followChannel") say(await attempt(() => m.followChannel(base, ...args)));
  if (name === "unfollow") say(await attempt(() => m.unfollow(base, args[0])));
}
process.exit(0);
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
    out = tmp_path_factory.mktemp("follow_pages")
    for name, entry in (("home", "videos"), ("video", "video-page"), ("channels", "channels")):
        _esbuild(FRONTEND / "src" / "pages" / entry / "index.ts", out / f"{name}.mjs")
    (out / "runner.mjs").write_text(PAGE_RUNNER)
    return out


def _seeds(page_html: str) -> dict[str, dict]:
    """Every `<button id=...>` in a page's HTML, with its text and its disabled and hidden state, so the page module starts from its own markup."""
    seeds = {}
    for attrs, inner in re.findall(r"<button\b([^>]*)>([\s\S]*?)</button>", (FRONTEND / page_html).read_text()):
        found = re.search(r'\bid="([^"]+)"', attrs)
        if found:
            seeds[found.group(1)] = {"tag": "button", "text": html.unescape(re.sub(r"<[^>]+>", "", inner)).strip(),
                                     "disabled": bool(re.search(r"\sdisabled\b", attrs)), "hidden": bool(re.search(r"\shidden\b", attrs))}
    return seeds


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


# --- C1: the cursor pager, driven with a scripted fetchPage ---


@pytest.fixture(scope="module")
def pager_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("cursor_pager")
    (out / "entry.ts").write_text(f'export {{ createCursorPager }} from "{FRONTEND}/src/data/videos.ts";\n')
    _esbuild(out / "entry.ts", out / "bundle.mjs")
    (out / "runner.mjs").write_text(PAGER_RUNNER)
    return out


def _pager(pager_bundle: Path, script: list[dict], calls: int) -> list[dict]:
    results = json.loads(_node(pager_bundle / "runner.mjs", {"BUNDLE": str(pager_bundle / "bundle.mjs"), "SCRIPT": json.dumps(script), "CALLS": str(calls)}).splitlines()[-1])
    # control: every next() settled
    assert len(results) == calls, results
    return results


def _rows(*ids: str) -> list[dict]:
    return [{"video_id": i, "instance_domain": "peer.example"} for i in ids]


def test_the_cursor_pager_walks_an_empty_page_resolves_a_short_one_and_is_exhausted_only_by_a_page_with_no_cursor(pager_bundle):
    script = [
        {"page": {"rows": _rows("a1", "a2", "a3"), "cursor": "c1"}},
        {"page": {"rows": [], "cursor": "c2"}},
        {"page": {"rows": _rows("b1"), "cursor": "c3"}},
        {"page": {"rows": _rows("d1")}},
    ]
    first, second, third, fourth = _pager(pager_bundle, script, 4)

    assert first == {"rows": ["a1", "a2", "a3"], "exhausted": False, "asked": [None]}, first  # C1
    # The empty page carried a cursor, so one next() asks again with it and resolves with the short page's row; createFeedPager's rule ends the feed here with no rows, and a short-page rule reads exhausted.
    assert second == {"rows": ["b1"], "exhausted": False, "asked": [None, "c1", "c2"]}, second  # C1
    # The page with no cursor ends the feed and its row is still served.
    assert third == {"rows": ["d1"], "exhausted": True, "asked": [None, "c1", "c2", "c3"]}, third  # C1
    # Exhausted, the pager asks nothing more: a fifth fetch would read "not scripted" here.
    assert fourth == {"rows": [], "exhausted": True, "asked": [None, "c1", "c2", "c3"]}, fourth  # C1


def test_an_empty_page_with_a_null_cursor_ends_the_walk_instead_of_asking_again(pager_bundle):
    script = [{"page": {"rows": _rows("a1"), "cursor": "c1"}}, {"page": {"rows": [], "cursor": None}}]
    first, second = _pager(pager_bundle, script, 2)

    assert first == {"rows": ["a1"], "exhausted": False, "asked": [None]}, first  # C1
    # A walk that keeps going through every empty page asks a third time and reads "not scripted".
    assert second == {"rows": [], "exhausted": True, "asked": [None, "c1"]}, second  # C1


def test_a_fetch_that_throws_leaves_the_cursor_so_the_next_call_asks_for_the_same_page(pager_bundle):
    script = [{"page": {"rows": _rows("a1"), "cursor": "c1"}}, {"throw": "Too many requests"}, {"page": {"rows": _rows("b1")}}]
    first, failed, retried = _pager(pager_bundle, script, 3)

    assert first == {"rows": ["a1"], "exhausted": False, "asked": [None]}, first  # C1
    # createFeedPager's rule exhausts on a failed fetch.
    assert failed == {"error": "Too many requests", "exhausted": False, "asked": [None, "c1"]}, failed  # C1
    # A pager that drops the cursor asks for the first page again (None); one that exhausted asks nothing.
    assert retried == {"rows": ["b1"], "exhausted": True, "asked": [None, "c1", "c1"]}, retried  # C1


# --- follows.ts against the real Client and Engine: the list the labels come from, and the toggles that change it ---


@pytest.fixture
def follows_runner(engine_client, tmp_path) -> Path:
    profile = f'export * from "{FRONTEND}/src/data/profile.ts";\n'
    (tmp_path / "entry.ts").write_text(profile + f'export * from "{FRONTEND}/src/data/follows.ts";\n')
    if not _esbuild(tmp_path / "entry.ts", tmp_path / "bundle.mjs", engine_client.base, check=False):
        # follows.ts is the module this phase adds. Without it the bundle carries profile.ts alone, so each follows call rejects with "m.<name> is not a function" and the assertions on those results read that, rather than the test ending at setup.
        (tmp_path / "entry.ts").write_text(profile)
        _esbuild(tmp_path / "entry.ts", tmp_path / "bundle.mjs", engine_client.base)
    (tmp_path / "runner.mjs").write_text(FOLLOWS_RUNNER)
    return tmp_path


def _follows(runner_dir: Path, base: str, steps: list[list]) -> list[dict]:
    out = _node(runner_dir / "runner.mjs", {"BASE": base, "BUNDLE": str(runner_dir / "bundle.mjs"), "STEPS": json.dumps(steps)})
    return [json.loads(line) for line in out.splitlines()]


def _keyset(follows: list[dict]) -> set[tuple]:
    return {tuple(_key_fields(f).values()) for f in follows}


def test_follows_ts_follows_a_video_s_channel_and_account_and_a_named_channel_lists_them_and_unfollows_one_through_the_real_client(engine_client, dataset, follows_runner):
    status, body = engine_client.request("GET", "/api/v1/search/videos?q=music")
    assert status == 200 and body["rows"], body
    video = body["rows"][0]
    mine = identity_of(dataset, video["video_id"], video["instance_domain"])
    # A second search row on another channel and another account, followed by its channel key alone.
    other = next(r for r in body["rows"] if (r["instance_domain"], r["channel_id"]) != (video["instance_domain"], mine["channel_id"]) and r["account_url"] != mine["account_url"])
    theirs = identity_of(dataset, other["video_id"], other["instance_domain"])
    channel_key = {"kind": "channel", "instance_domain": video["instance_domain"], "channel_id": mine["channel_id"], "account_url": ""}
    account_key = {"kind": "account", "instance_domain": "", "channel_id": "", "account_url": mine["account_url"]}
    named_key = {"kind": "channel", "instance_domain": other["instance_domain"], "channel_id": theirs["channel_id"], "account_url": ""}

    _key, by_channel, by_account, named, listed, unfollowed, relisted = _follows(follows_runner, engine_client.base, [
        ["create"], ["followVideo", "channel", video["video_uuid"], video["instance_domain"]], ["followVideo", "account", video["video_uuid"], video["instance_domain"]],
        ["followChannel", other["instance_domain"], theirs["channel_id"]], ["list"], ["unfollow", channel_key], ["list"],
    ])

    # Each add resolves with the stored follow, keyed as whitelist.db keys the video's channel, its account and the named channel.
    assert _key_fields(by_channel.get("ok")) == channel_key, by_channel  # C2
    assert _key_fields(by_account.get("ok")) == account_key, by_account  # C2
    assert _key_fields(named.get("ok")) == named_key, named  # C2
    assert "ok" in listed and _keyset(listed["ok"]) == {tuple(k.values()) for k in (channel_key, account_key, named_key)}, listed  # C2
    assert unfollowed == {"ok": None}, unfollowed  # C2
    # Only the channel followed through the video is gone; an unfollow that sends the wrong key leaves three, one that matches loosely takes the named channel too.
    assert "ok" in relisted and _keyset(relisted["ok"]) == {tuple(k.values()) for k in (account_key, named_key)}, relisted  # C2


@pytest.mark.parametrize("stored", [secrets.token_urlsafe(32), None], ids=["unknown-key", "no-key"])
def test_every_follows_ts_call_the_client_answers_401_rejects_with_profile_key_required(engine_client, follows_runner, stored):
    key_step = [["store", stored]] if stored else []
    target = {"kind": "channel", "instance_domain": "tube.example", "channel_id": "1", "account_url": ""}
    out = _follows(follows_runner, engine_client.base, [*key_step, ["list"], ["followVideo", "channel", "uuid-x", "tube.example"], ["followChannel", "tube.example", "1"], ["unfollow", target]])
    results = out[len(key_step):]

    # The Client answers each of these 401 {"error": "Profile key required"} (observed); a module that swallows it resolves, and one that replaces the message reads otherwise.
    assert results == [{"error": "Profile key required"}] * 4, results  # C2


# --- C2: the home feed's cards ---


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


# --- C2: the video page's two buttons ---


VIDEO_SEARCH = "?id=v1&host=peer.example"
VIDEO_BODY = {"videoUuid": "uuid-1", "title": "Follow fixture", "channelName": "Video channel", "channelId": "ch-v", "accountName": "Alice", "accountUrl": ALICE}


def _video_answers(**extra) -> dict:
    # The page reads its reaction, comments, similars and instance details too; those answer 200 {} as in test_frontend_video_page.py.
    return {"default": {"status": 200, "body": {}}, "GET /api/video": {"body": VIDEO_BODY}, **extra}


def _video_follow(snapshot: dict) -> tuple:
    return snapshot["follow"]["channel"], snapshot["follow"]["account"]


def test_the_video_page_s_buttons_are_labelled_from_the_follow_list_flip_on_each_toggle_and_a_block_resets_the_channel(pages):
    answers = _video_answers(**{
        "GET /api/profile/follows": {"body": {"follows": [_channel(PEER, "ch-v", "Video channel")]}},
        "POST /api/profile/follows": [{"status": 201, "body": {"follow": _account(ALICE, "Alice")}}, {"status": 201, "body": {"follow": _channel(PEER, "ch-v", "Video channel")}}],
        "POST /api/profile/blocks": [{"status": 201, "body": {"block": _channel(PEER, "ch-v", "Video channel")}}],
        "POST /api/profile/follows/remove": [{"status": 204}],
    })
    page = _page(pages, "video", storage=KEY_STORAGE, search=VIDEO_SEARCH, pathname="/video-page.html", seeds=_seeds("video-page.html"), answers=answers,
                 steps=[{"click": "Follow account"}, {"click": "Block channel"}, {"click": "Follow channel"}, {"click": "Unfollow account"}])
    loaded, account_on, blocked, channel_on, account_off = page["snapshots"]
    steps = page["steps"]

    # The channel is in the list and the account is not; without channelId in /api/video, or without the list, the channel reads "Follow channel".
    assert _video_follow(loaded) == (["Unfollow channel"], ["Follow account"]), (loaded["follow"], page["rejections"])  # C2
    assert steps[0]["dispatched"] and [(r["path"], _video_form(r["body"])) for r in _sent(steps[0])] == [
        ("/api/profile/follows", {"kind": "account", "uuid": "uuid-1", "host": PEER, "instance_domain": None, "channel_id": None})], steps[0]  # C2
    assert _video_follow(account_on) == (["Unfollow channel"], ["Unfollow account"]), (account_on["follow"], page["rejections"])  # C2
    # control: the block was sent, as today's page sends it
    assert steps[1]["dispatched"] and "/api/profile/blocks" in [r["path"] for r in steps[1]["requests"]], steps[1]
    # The Client drops the follow on a blocked key, so the channel button resets; the account follow is another key and stays.
    assert _video_follow(blocked) == (["Follow channel"], ["Unfollow account"]), (blocked["follow"], page["rejections"])  # C2
    assert steps[2]["dispatched"] and [(r["path"], _video_form(r["body"])) for r in _sent(steps[2])] == [
        ("/api/profile/follows", {"kind": "channel", "uuid": "uuid-1", "host": PEER, "instance_domain": None, "channel_id": None})], steps[2]  # C2
    assert _video_follow(channel_on) == (["Unfollow channel"], ["Unfollow account"]), (channel_on["follow"], page["rejections"])  # C2
    assert steps[3]["dispatched"] and [(r["path"], _key_fields(r["body"])) for r in _sent(steps[3])] == [
        ("/api/profile/follows/remove", {"kind": "account", "instance_domain": "", "channel_id": "", "account_url": ALICE})], steps[3]  # C2
    assert _video_follow(account_off) == (["Unfollow channel"], ["Follow account"]), (account_off["follow"], page["rejections"])  # C2


def test_keyless_video_page_follow_buttons_send_nothing_and_say_following_needs_a_profile_on_the_home_page(pages):
    page = _page(pages, "video", storage={}, search=VIDEO_SEARCH, pathname="/video-page.html", seeds=_seeds("video-page.html"), answers=_video_answers(),
                 steps=[{"click": "Follow channel"}, {"click": "Block channel"}, {"click": "Follow account"}])
    # A fresh page clicked on the account button alone, so the message it shows cannot be one the channel click left behind.
    alone = _page(pages, "video", storage={}, search=VIDEO_SEARCH, pathname="/video-page.html", seeds=_seeds("video-page.html"), answers=_video_answers(), steps=[{"click": "Follow account"}])
    loaded, channel, blocked, account = page["snapshots"]
    alone_loaded, alone_account = alone["snapshots"]
    steps = page["steps"]

    # control: the page wired its block buttons, which answer a keyless click with their own wording (observed today)
    assert steps[1]["dispatched"] and "Blocking needs a profile. Create one from the Profile button on the home page." in blocked["texts"], (steps[1], page["rejections"])
    assert _video_follow(loaded) == (["Follow channel"], ["Follow account"]), (loaded["follow"], page["rejections"])  # C2
    # The buttons start disabled in the markup, so an unwired button is never dispatched.
    assert steps[0]["dispatched"] and NEEDS_PROFILE_VIDEO_PAGE in channel["texts"], (steps[0], page["rejections"])  # C2
    # control: the message is not on the page before any follow click
    assert NEEDS_PROFILE_VIDEO_PAGE not in loaded["texts"] and NEEDS_PROFILE_VIDEO_PAGE not in alone_loaded["texts"], (loaded["texts"], alone_loaded["texts"])
    # An account handler that shows nothing leaves the fresh page without the message.
    assert alone["steps"][0]["dispatched"] and NEEDS_PROFILE_VIDEO_PAGE in alone_account["texts"], (alone["steps"][0], alone["rejections"])  # C2
    assert steps[2]["dispatched"] and _video_follow(account) == (["Follow channel"], ["Follow account"]), (steps[2], account["follow"])  # C2
    assert _video_follow(alone_account) == (["Follow channel"], ["Follow account"]), alone_account["follow"]  # C2
    assert _follows_paths(page["requests"]) == [] and _follows_paths(alone["requests"]) == [], (page["requests"], alone["requests"])  # C2


# --- C2: the channels page's row button ---


CHANNEL_NAMES = ["Lofi Beats Radio", "Rain Sounds", "Night Drive"]


def _channel_row(channel_id: str, host: str, name: str) -> dict:
    return {"channel_id": channel_id, "channel_name": name.lower().replace(" ", "_"), "channel_url": None, "display_name": name, "instance_domain": host, "videos_count": 3, "followers_count": 12,
            "avatar_url": None, "health_status": None, "health_checked_at": None, "health_error": None, "last_error": None, "last_error_at": None, "last_error_source": None}


# The followed channel, another channel on its host, and one with the followed channel_id on another host.
CHANNEL_ROWS = [_channel_row("c1", "tube.example", CHANNEL_NAMES[0]), _channel_row("c2", "tube.example", CHANNEL_NAMES[1]), _channel_row("c1", "other.example", CHANNEL_NAMES[2])]


def _row_labels(snapshot: dict) -> dict[str, list[str]]:
    return {(r["names"] or ["?"])[0]: r["follow"] for r in snapshot["rows"]}


def _row_texts(snapshot: dict, name: str) -> list[str]:
    return next(r["texts"] for r in snapshot["rows"] if name in r["names"])


def test_channels_rows_are_labelled_from_the_follow_list_and_flip_on_follow_and_unfollow_but_not_on_a_refusal(pages):
    lofi, rain, night = CHANNEL_NAMES
    answers = {
        "GET /api/channels": {"body": {"rows": CHANNEL_ROWS, "total": 3}},
        "GET /api/profile/follows": {"body": {"follows": [_channel("tube.example", "c1", lofi)]}},
        "POST /api/profile/follows": [{"status": 201, "body": {"follow": _channel("tube.example", "c2", rain)}}, {"status": 400, "body": {"error": LIMIT_ERROR}}],
        "POST /api/profile/follows/remove": [{"status": 204}],
    }
    page = _page(pages, "channels", storage=KEY_STORAGE, answers=answers, held=["/api/channels"], row_names=CHANNEL_NAMES,
                 steps=[{"row": rain, "click": "Follow"}, {"row": lofi, "click": "Unfollow"}, {"row": night, "click": "Follow"}])
    loaded, followed, unfollowed, refused = page["snapshots"]
    steps = page["steps"]

    # control: one table row per channel
    assert [r["names"] for r in loaded["rows"]] == [[lofi], [rain], [night]], (loaded, page["rejections"])
    # A lookup keyed by channel_id alone also marks Night Drive.
    assert _row_labels(loaded) == {lofi: ["Unfollow"], rain: ["Follow"], night: ["Follow"]}, (loaded, page["rejections"])  # C2
    # The row has no video, so the follow names the channel by its key alone.
    assert steps[0]["dispatched"] and [(r["path"], r["body"]) for r in _sent(steps[0])] == [
        ("/api/profile/follows", {"kind": "channel", "instance_domain": "tube.example", "channel_id": "c2"})], steps[0]  # C2
    assert _row_labels(followed) == {lofi: ["Unfollow"], rain: ["Unfollow"], night: ["Follow"]}, (followed, page["rejections"])  # C2
    assert steps[1]["dispatched"] and [(r["path"], _key_fields(r["body"])) for r in _sent(steps[1])] == [
        ("/api/profile/follows/remove", {"kind": "channel", "instance_domain": "tube.example", "channel_id": "c1", "account_url": ""})], steps[1]  # C2
    assert _row_labels(unfollowed) == {lofi: ["Follow"], rain: ["Unfollow"], night: ["Follow"]}, (unfollowed, page["rejections"])  # C2
    # A refused follow keeps "Follow" and shows the Client's error in its row.
    assert steps[2]["dispatched"] and [r["path"] for r in _sent(steps[2])] == ["/api/profile/follows"], steps[2]
    assert _row_labels(refused) == _row_labels(unfollowed) and LIMIT_ERROR in _row_texts(refused, night), (refused, page["rejections"])  # C2
    assert _follows_paths(page["requests"]).count("GET /api/profile/follows") == 1, page["requests"]  # C2


def test_keyless_channels_rows_read_follow_and_a_click_sends_nothing_and_says_following_needs_a_profile(pages):
    lofi = CHANNEL_NAMES[0]
    page = _page(pages, "channels", storage={}, answers={"GET /api/channels": {"body": {"rows": CHANNEL_ROWS, "total": 3}}}, held=["/api/channels"], row_names=CHANNEL_NAMES,
                 steps=[{"row": lofi, "click": "Follow"}])
    loaded, clicked = page["snapshots"]

    # control: the table rendered its rows
    assert [r["names"] for r in loaded["rows"]] == [[n] for n in CHANNEL_NAMES], (loaded, page["rejections"])
    assert _row_labels(loaded) == {n: ["Follow"] for n in CHANNEL_NAMES}, (loaded, page["rejections"])  # C2
    assert page["steps"][0]["dispatched"] and NEEDS_PROFILE in _row_texts(clicked, lofi), (clicked, page["rejections"])  # C2
    assert _row_labels(clicked) == _row_labels(loaded), clicked  # C2
    assert _follows_paths(page["requests"]) == [], page["requests"]  # C2
