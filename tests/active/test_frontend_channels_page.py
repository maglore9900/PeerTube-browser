"""A channels table row marks its instance domain with `channel-domain`, the class `channels.css` styles it with, and carries no `channel-meta`.

The channels page module (`src/pages/channels/index.ts`) runs in node on an esbuild bundle against a stubbed browser platform: a `document` holding plain recording elements for the four ids the module requires, `window.location`, and `fetch`, which answers `/api/channels` with a one-row payload and 404 for anything else. The rendered `#channels-body` is read once the load settles.

Each row's follow button, with the module bundled and run in node on a recording DOM that parses innerHTML (`DOM_JS` + `PAGE_RUNNER`), so the delegated click, `closest` and `querySelector` work; `fetch` is stubbed per case and the channel list is answered only after the follow list:
- Keyed, with a list holding c1 on tube.example, its row reads "Unfollow"; c2 on tube.example and c1 on other.example read "Follow". Follow on c2 posts `{kind: "channel", instance_domain, channel_id}` and flips. Unfollow on c1 posts its key to remove and flips. A refused Follow keeps "Follow" and shows the error in its row. The list is fetched once.
- Keyless, every row reads "Follow". A click shows "Following needs a profile. Create one from the Profile button." in its row and sends nothing to the follow routes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
CHANNEL = "Lofi Beats Radio"
DOMAIN = "tube.example"
CHANNEL_ROW = {"channel_id": "c1", "channel_name": "lofi_beats", "channel_url": None, "display_name": CHANNEL, "instance_domain": DOMAIN,
               "videos_count": 3, "followers_count": 12, "avatar_url": None, "health_status": None, "health_checked_at": None, "health_error": None,
               "last_error": None, "last_error_at": None, "last_error_source": None}

CHANNELS_RUNNER = """
const element = () => ({ innerHTML: "", textContent: "", addEventListener() {} });
const byId = new Map(["channels-body", "summary-counts", "summary-meta", "page-status"].map((id) => [id, element()]));
globalThis.window = { location: { origin: process.env.BASE, search: "" }, setTimeout, clearTimeout };
globalThis.document = { getElementById: (id) => byId.get(id) ?? null, querySelectorAll: () => [] };
const requested = [];
globalThis.fetch = async (input) => {
  const url = new URL(String(input), process.env.BASE);
  requested.push(url.pathname);
  if (url.pathname === "/api/channels") return new Response(process.env.PAYLOAD, { status: 200, headers: { "content-type": "application/json" } });
  return new Response("{}", { status: 404 });
};
await import(process.env.BUNDLE);
// The stubbed fetch resolves at once, so the page's load has rendered within a few macrotasks.
for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
process.stdout.write(JSON.stringify({ requested, body: byId.get("channels-body").innerHTML }) + "\\n");
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("channels_page")
    defines = [f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"]
    subprocess.run([str(ESBUILD), str(FRONTEND / "src" / "pages" / "channels" / "index.ts"), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'channels.mjs'}", *defines],
                   check=True, capture_output=True)
    (out / "channels_runner.mjs").write_text(CHANNELS_RUNNER)
    return out


def test_the_channels_row_carries_channel_domain_on_its_instance_domain_and_no_channel_meta(bundle):
    proc = subprocess.run(["node", str(bundle / "channels_runner.mjs")], capture_output=True, text=True, timeout=60,
                          env={"BASE": BASE, "BUNDLE": str(bundle / "channels.mjs"), "PAYLOAD": json.dumps({"rows": [CHANNEL_ROW], "total": 1}), "PATH": os.environ.get("PATH", "")})
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    body = page["body"]

    # control: the page asked for its channels and rendered the row, so an empty or loading table cannot pass
    assert "/api/channels" in page["requested"], page["requested"]
    assert CHANNEL in body and DOMAIN in body, body
    assert re.search(r'class="channel-domain"[^>]*>\s*' + re.escape(DOMAIN) + r"\s*<", body), body
    assert "channel-meta" not in body, body


# --- the row follow button, on a recording DOM that parses innerHTML ---

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
    """The channels page module bundled as `channels.mjs`, beside the follow-control runner."""
    out = tmp_path_factory.mktemp("follow_pages")
    _esbuild(FRONTEND / "src" / "pages" / "channels" / "index.ts", out / "channels.mjs")
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


def _channel(host: str, channel_id: str, label: str) -> dict:
    return {"kind": "channel", "instance_domain": host, "channel_id": channel_id, "account_url": "", "label": label, "created_at": 1}


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
