"""The search page runs a URL carrying a `tag` and no `q` in tag mode, requesting only `tag`, and any `q`, from the box or the URL, replaces tag mode with a text search that drops `tag` from the request and the URL.

`pages/search/index.ts` is bundled with `data/search.ts` (production build) and run in node on a recording DOM parsed from the body of the real `search.html`; an id the page looks up that the markup lacks is created on demand and listed, never thrown. `fetch` answers each search request with the next scripted page, each page's video ids its own, `window.history` records `pushState`/`replaceState` and moves `window.location` as a browser would, and a `popstate` step moves `window.location` and fires the window's listeners. After each phase the runner reads the keys of the cards in `#search-results` and the address. Request and address-bar URLs are parsed with `urllib.parse`.

Tag mode (C1), entered three ways:
- A load of `?tag=Linux` requests `tag=Linux` with no `q` at `sort=published_at` and renders exactly that answer's two cards. `#search-tag` is shown and names Linux, the title is `Linux - Tag - Search - PeerTube - Browser`, the relevance option is hidden and disabled, and the status reads `Showing 2 of 5 videos tagged "Linux".`. Every element the page looks up, the heading included, is in the real `search.html`.
- From a load of `?tag=Linux&sort=popularity`, a sort change to `views` requests `tag=Linux` with no `q` at `views`, replaces the grid with exactly that answer's three cards, pushes `?tag=Linux&sort=views`, keeps the heading, title and relevance option of tag mode, and reads `Showing 3 of 7 videos tagged "Linux".`. A change to `published_at` then pushes `?tag=Linux` with no `sort`, and an empty answer empties the grid and reads `No videos tagged "Linux".`.
- From a load of `?q=music`, a `popstate` into `?tag=Linux&sort=views` requests `tag=Linux` with no `q` at `views`, replaces the music cards with exactly the tag answer's four, writes no history entry, shows the heading, title and relevance option of tag mode, and reads `Showing 4 of 6 videos tagged "Linux".`. A `popstate` to a bare `/search.html` then shows the idle line and writes no history entry.
- From a load of `?tag=Linux`, a `popstate` into `?tag=a+b%26c` requests the tag `a b&c` (decoded) with no `q` at `published_at`, replaces the Linux cards with exactly that answer's one, shows a heading that names `a b&c` and not Linux, the title `a b&c - Tag - Search - PeerTube - Browser` and `Showing 1 of 3 videos tagged "a b&c".`, and writes no history entry. A sort change to `views` then requests `a b&c` at `views`, shows that answer's two cards, and pushes a URL that reads back as `tag=a b&c`, `sort=views`.

Text search over tag mode (C2):
- From tag mode, a box submit of `music` requests `q=music` with no `tag`, pushes one URL with `q=music` and no `tag`, shows and enables the relevance option, hides the heading, and reads `Showing 3 of 8 matched videos.` under the title `music - Search - PeerTube - Browser`.
- A load of `?q=music&tag=Linux` requests `q=music` with no `tag`, makes one history call, a `replaceState` to a URL with `q=music` and no `tag`, hides the heading, and reads `Showing 2 of 9 matched videos.`.
- From tag mode on `a b&c`, a `popstate` into `?q=music&tag=Linux` requests `q=music` with no `tag`, shows and enables the relevance option, hides the heading, reads `Showing 3 of 8 matched videos.`, and leaves the address at `/search.html` with `q=music` and no `tag` through one history call, a `replaceState`.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
BASE = "http://client.test"
SEARCH_PATH = "/api/v1/search/videos"
TITLE = "Linux - Tag - Search - PeerTube - Browser"
IDLE = "Enter a search term to begin."

# The recording DOM of tests/active/test_frontend_videos_page.py (DOM_JS): innerHTML is parsed into elements, so `querySelector('option[value="relevance"]')` finds the select's option, and `hidden` and `disabled` are attributes.
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

# The search page on the DOM of search.html's body. `fetch` answers each search request with the next of ANSWERS (500 once they run out) and anything else with `{}`. `history` records each call with the address it leaves, resolved against the current one as a browser does. Each STEPS entry submits the box, changes the sort or moves the address and fires `popstate`; after the load and after each step it reports the requests and history calls made in it, what the page shows, the video keys of the cards in the grid, and the address. A throw, a rejection and an id the markup lacks come back as data.
SEARCH_RUNNER = DOM_JS + r"""
const env = process.env;
const memory = () => { const s = new Map(); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
const errors = [];
process.on("unhandledRejection", (r) => { errors.push(String((r && r.stack) || r)); });
const location = { origin: env.BASE, pathname: "/search.html", search: env.SEARCH };
const move = (url) => { const next = new URL(String(url), location.origin + location.pathname + location.search); location.pathname = next.pathname; location.search = next.search; return next.pathname + next.search; };
const history = [];
const windowListeners = {};
globalThis.window = { location, localStorage, sessionStorage, innerHeight: 800, scrollY: 0, confirm: () => true, setTimeout, clearTimeout,
  addEventListener: (type, l) => { (windowListeners[type] ??= []).push(l); }, removeEventListener() {},
  history: { pushState: (state, title, url) => { history.push({ kind: "push", url: move(url) }); }, replaceState: (state, title, url) => { history.push({ kind: "replace", url: move(url) }); } } };
const body = element("body");
body.root = true;
body.innerHTML = env.HTML;
const missing = [];
const created = new Map();
const byId = (id) => descendants(body).find((n) => n.attrs.id === id) ?? created.get(id) ?? (() => { const el = element("div"); el.root = true; el.attrs.id = id; created.set(id, el); missing.push(id); return el; })();
globalThis.document = { title: "", body, documentElement: { scrollHeight: 100000, clientHeight: 800 }, getElementById: byId, createElement: (t) => element(t), createTextNode: (v) => textNode(v),
  querySelector: (s) => descendants(body).find((n) => matches(n, s)) ?? null, querySelectorAll: (s) => descendants(body).filter((n) => matches(n, s)), addEventListener() {} };
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
const answers = JSON.parse(env.ANSWERS);
const requests = [];
globalThis.fetch = async (input) => { const url = new URL(String(input?.url ?? input), env.BASE); requests.push(url.pathname + url.search);
  const searching = url.pathname === env.SEARCH_PATH; const answer = searching ? answers.shift() : {};
  return new Response(JSON.stringify(answer ?? { error: "not scripted" }), { status: answer === undefined ? 500 : 200, headers: { "content-type": "application/json" } }); };
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 10)); };
const call = (listeners, self, event) => { for (const l of [...(listeners ?? [])]) { try { l.call(self, event); } catch (e) { errors.push(String((e && e.stack) || e)); } } };
const fire = (target, type) => { const event = { type, target, bubbles: true, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() {} };
  for (let node = target; node; node = node.parentElement) { event.currentTarget = node; call(node.listeners[type], node, event); } };
const phases = [];
let seen = { requests: 0, history: 0 };
const record = (name) => { const heading = byId("search-tag"); const relevance = byId("search-sort").querySelector('option[value="relevance"]');
  phases.push({ name, requests: requests.slice(seen.requests), history: history.slice(seen.history), title: document.title, status: byId("search-status").textContent,
    heading: { hidden: heading.hidden, text: heading.textContent }, relevance: relevance ? { hidden: relevance.hidden, disabled: relevance.disabled } : null,
    cards: byId("search-results").querySelectorAll(".video-card").map((card) => card.dataset.videoKey ?? null), address: location.pathname + location.search });
  seen = { requests: requests.length, history: history.length }; };
try { await import(env.BUNDLE); } catch (e) { errors.push(String((e && e.stack) || e)); }
await settle();
record("load");
for (const step of JSON.parse(env.STEPS)) {
  if ("submit" in step) { byId("search-input").value = step.submit; fire(byId("search-form"), "submit"); }
  else if ("sort" in step) { byId("search-sort").value = step.sort; fire(byId("search-sort"), "change"); }
  else { move(step.popstate); call(windowListeners.popstate, window, { type: "popstate", state: {} }); }
  await settle();
  record(JSON.stringify(step));
}
process.stdout.write(JSON.stringify({ phases, errors, missing }) + "\n", () => process.exit(0));
"""


def _prepare(frontend: Path, out: Path) -> Path:
    """The search page of `frontend` built for production as `bundle.mjs`, the body of its `search.html` as `body.html`, and the runner beside them."""
    run = subprocess.run([str(FRONTEND / "node_modules" / ".bin" / "esbuild"), str(frontend / "src" / "pages" / "search" / "index.ts"), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty",
                          f"--outfile={out / 'bundle.mjs'}", f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-2000:]
    html = (frontend / "search.html").read_text()
    (out / "body.html").write_text(html[html.index("<body>") + len("<body>"):html.index("</body>")])
    (out / "runner.mjs").write_text(SEARCH_RUNNER)
    return out


@pytest.fixture(scope="module")
def page(tmp_path_factory) -> Path:
    return _prepare(FRONTEND, tmp_path_factory.mktemp("search_page"))


def _run(page: Path, search: str, answers: list[dict], steps: list[dict] = ()) -> dict:
    proc = subprocess.run(["node", str(page / "runner.mjs")], capture_output=True, text=True, timeout=60,
                          env={"PATH": os.environ.get("PATH", ""), "BASE": BASE, "BUNDLE": str(page / "bundle.mjs"), "HTML": (page / "body.html").read_text(), "SEARCH": search,
                               "SEARCH_PATH": SEARCH_PATH, "ANSWERS": json.dumps(answers), "STEPS": json.dumps(list(steps))})
    assert proc.returncode == 0, proc.stderr[-4000:]
    report = json.loads(proc.stdout.splitlines()[-1])
    assert [phase["name"] for phase in report["phases"]] == ["load", *(json.dumps(step, separators=(",", ":")) for step in steps)], report
    return report


def _answer(name: str, rows: int, total: int) -> dict:
    # views and likes on a row keep the card from asking the instance for live stats; `name` makes each answer's video ids its own, so a card left from another answer shows
    return {"rows": [{"video_id": f"{name}-{i}", "video_uuid": f"{name}-{i}", "instance_domain": "peer.example", "title": f"Video {name} {i}", "views": 1, "likes": 1} for i in range(rows)], "total": total}


def _searches(phase: dict) -> list[dict]:
    """Each search request of a phase as its parsed query, blanks kept, so an empty `q=` still reads as sent."""
    return [parse_qs(urlsplit(url).query, keep_blank_values=True) for url in phase["requests"] if urlsplit(url).path == SEARCH_PATH]


def _history(phase: dict) -> list[tuple[str, str, dict]]:
    """Each history call of a phase as its kind and the address it left, path and parsed query."""
    return [(entry["kind"], urlsplit(entry["url"]).path, parse_qs(urlsplit(entry["url"]).query, keep_blank_values=True)) for entry in phase["history"]]


def test_a_tag_url_loads_that_tags_results_in_tag_mode_requested_with_tag_and_no_q(page):
    report = _run(page, "?tag=Linux", [_answer("linux", 2, 5)])
    load = report["phases"][0]
    why = (report["errors"], report["missing"], load)

    # today a URL with no q goes idle and requests nothing; a request built as today's sends `q=` beside the tag, and a tag mode defaulting to relevance sends sort=relevance
    assert [(query.get("tag"), "q" in query, query.get("sort")) for query in _searches(load)] == [(["Linux"], False, ["published_at"])], why  # C1
    # a tag branch that sets the status without rendering leaves the grid empty
    assert load["cards"] == ["peer.example::linux-0", "peer.example::linux-1"], why  # C1
    assert load["heading"]["hidden"] is False and "Linux" in load["heading"]["text"], why  # C1
    assert load["title"] == TITLE, why  # C1
    # a relevance option only hidden can still be chosen by keyboard; only disabled, it still shows in the menu
    assert load["relevance"] == {"hidden": True, "disabled": True}, why  # C1
    # the text wording here reads "Showing 2 of 5 matched videos."
    assert load["status"] == 'Showing 2 of 5 videos tagged "Linux".', why  # C1
    # the heading came from the real search.html, not from the harness making up an element the page looked for
    assert report["missing"] == [], why  # C1


def test_a_sort_change_in_tag_mode_requests_the_tag_at_the_new_sort_and_writes_sort_into_the_url_only_off_published_at(page):
    report = _run(page, "?tag=Linux&sort=popularity", [_answer("popular", 2, 5), _answer("viewed", 3, 7), _answer("newest", 0, 0)], [{"sort": "views"}, {"sort": "published_at"}])
    load, views, newest = report["phases"]
    why = (report["errors"], report["missing"])

    assert [(query.get("tag"), "q" in query, query.get("sort")) for query in _searches(load)] == [(["Linux"], False, ["popularity"])], (why, load)  # C1
    assert load["cards"] == ["peer.example::popular-0", "peer.example::popular-1"], (why, load)  # C1
    # today's handler ignores a change while there is no q, so nothing is requested or pushed
    assert [(query.get("tag"), "q" in query, query.get("sort")) for query in _searches(views)] == [(["Linux"], False, ["views"])], (why, views)  # C1
    # a re-sort that appends instead of replacing keeps the popular cards ahead of these
    assert views["cards"] == ["peer.example::viewed-0", "peer.example::viewed-1", "peer.example::viewed-2"], (why, views)  # C1
    # a push without tag would land the reload on the idle page
    assert _history(views) == [("push", "/search.html", {"tag": ["Linux"], "sort": ["views"]})], (why, views)  # C1
    assert views["heading"]["hidden"] is False and "Linux" in views["heading"]["text"], (why, views)  # C1
    assert views["title"] == TITLE, (why, views)  # C1
    assert views["relevance"] == {"hidden": True, "disabled": True}, (why, views)  # C1
    assert views["status"] == 'Showing 3 of 7 videos tagged "Linux".', (why, views)  # C1
    assert [(query.get("tag"), "q" in query, query.get("sort")) for query in _searches(newest)] == [(["Linux"], False, ["published_at"])], (why, newest)  # C1
    # an empty answer that never clears the grid leaves the viewed cards under a "No videos" line
    assert newest["cards"] == [], (why, newest)  # C1
    # a URL that leaves sort out only at relevance, as text search does, writes sort=published_at here
    assert _history(newest) == [("push", "/search.html", {"tag": ["Linux"]})], (why, newest)  # C1
    # the text wording here reads 'No results for "".'
    assert newest["status"] == 'No videos tagged "Linux".', (why, newest)  # C1


def test_back_navigation_from_a_text_search_into_a_tag_url_shows_the_tag_and_back_to_a_bare_search_page_pushes_nothing(page):
    report = _run(page, "?q=music", [_answer("music", 2, 9), _answer("linux", 4, 6)], [{"popstate": "/search.html?tag=Linux&sort=views"}, {"popstate": "/search.html"}])
    load, back, bare = report["phases"]
    why = (report["errors"], report["missing"])

    # control: the page started in a text search, so the next step leaves one
    assert [(query.get("q"), "tag" in query) for query in _searches(load)] == [(["music"], False)] and load["status"] == "Showing 2 of 9 matched videos.", (why, load)
    # today's handler reads only q, so this entry goes idle and requests nothing
    assert [(query.get("tag"), "q" in query, query.get("sort")) for query in _searches(back)] == [(["Linux"], False, ["views"])], (why, back)  # C1
    # a handler that appends the page keeps the music cards ahead of the tag's
    assert back["cards"] == ["peer.example::linux-0", "peer.example::linux-1", "peer.example::linux-2", "peer.example::linux-3"], (why, back)  # C1
    assert back["heading"]["hidden"] is False and "Linux" in back["heading"]["text"], (why, back)  # C1
    assert back["title"] == TITLE, (why, back)  # C1
    assert back["relevance"] == {"hidden": True, "disabled": True}, (why, back)  # C1
    assert back["status"] == 'Showing 4 of 6 videos tagged "Linux".', (why, back)  # C1
    # the address bar already holds this entry; a handler that runs a fresh search pushes a duplicate and drops the forward history
    assert _history(back) == [], (why, back)  # C1
    # the positive half: the handler ran and went idle
    assert bare["status"] == IDLE, (why, bare)  # C1
    # an idle page that writes its URL as it does from the box pushes /search.html over the forward history
    assert _history(bare) == [], (why, bare)  # C1


def test_a_box_submit_from_tag_mode_runs_a_text_search_and_drops_tag_from_the_request_and_the_url(page):
    report = _run(page, "?tag=Linux&sort=views", [_answer("linux", 2, 5), _answer("music", 3, 8)], [{"submit": "music"}])
    load, submitted = report["phases"]
    why = (report["errors"], report["missing"])

    # the page was in tag mode before the submit, so what the submit undoes below was done
    assert [(query.get("tag"), "q" in query) for query in _searches(load)] == [(["Linux"], False)], (why, load)  # C1
    assert load["relevance"] == {"hidden": True, "disabled": True} and load["heading"]["hidden"] is False, (why, load)  # C1
    # a submit that keeps the tag sends tag=Linux, which wins over q, or both, which the Engine refuses
    assert [(query.get("q"), "tag" in query) for query in _searches(submitted)] == [(["music"], False)], (why, submitted)  # C2
    assert [(kind, path, query.get("q"), "tag" in query) for kind, path, query in _history(submitted)] == [("push", "/search.html", ["music"], False)], (why, submitted)  # C2
    # a submit that never re-runs the mode leaves relevance unselectable in a text search, and the heading naming a tag no longer searched
    assert submitted["relevance"] == {"hidden": False, "disabled": False}, (why, submitted)  # C2
    assert submitted["heading"]["hidden"] is True, (why, submitted)  # C2
    assert (submitted["status"], submitted["title"]) == ("Showing 3 of 8 matched videos.", "music - Search - PeerTube - Browser"), (why, submitted)  # C2


def test_a_url_with_q_and_tag_runs_the_text_search_and_replaces_the_url_with_one_without_tag(page):
    report = _run(page, "?q=music&tag=Linux", [_answer("music", 2, 9)])
    load = report["phases"][0]
    why = (report["errors"], report["missing"], load)

    # a page preferring the tag, or passing both on, sends tag=Linux here
    assert [(query.get("q"), "tag" in query) for query in _searches(load)] == [(["music"], False)], why  # C2
    # left in place, the address bar keeps a tag the page is not showing; pushed, back returns to it
    assert [(kind, path, query.get("q"), "tag" in query) for kind, path, query in _history(load)] == [("replace", "/search.html", ["music"], False)], why  # C2
    assert load["heading"]["hidden"] is True and load["status"] == "Showing 2 of 9 matched videos.", why  # C2


def test_back_navigation_into_another_tag_shows_that_tag_and_into_a_url_with_q_and_tag_runs_the_text_search_and_drops_tag_from_the_url(page):
    report = _run(page, "?tag=Linux", [_answer("linux", 2, 5), _answer("abc", 1, 3), _answer("abcviewed", 2, 3), _answer("music", 3, 8)],
                  [{"popstate": "/search.html?tag=a+b%26c"}, {"sort": "views"}, {"popstate": "/search.html?q=music&tag=Linux"}])
    load, other, resorted, mixed = report["phases"]
    why = (report["errors"], report["missing"])

    # the page was in tag mode on Linux, with its cards in the grid, so the next step moves off a tag already shown
    assert [(query.get("tag"), "q" in query) for query in _searches(load)] == [(["Linux"], False)], (why, load)  # C1
    assert load["cards"] == ["peer.example::linux-0", "peer.example::linux-1"], (why, load)  # C1
    # a handler that keeps the tag it loaded with sends tag=Linux; a tag put on the request unencoded splits at the `&` into `a b` and a stray `c`
    assert [(query.get("tag"), "q" in query, query.get("sort")) for query in _searches(other)] == [(["a b&c"], False, ["published_at"])], (why, other)  # C1
    # a handler that renders without resetting keeps the Linux cards ahead of this tag's
    assert other["cards"] == ["peer.example::abc-0"], (why, other)  # C1
    # a heading set once on the load still names Linux
    assert other["heading"]["hidden"] is False and "a b&c" in other["heading"]["text"] and "Linux" not in other["heading"]["text"], (why, other)  # C1
    assert other["title"] == "a b&c - Tag - Search - PeerTube - Browser", (why, other)  # C1
    assert other["status"] == 'Showing 1 of 3 videos tagged "a b&c".', (why, other)  # C1
    assert _history(other) == [], (why, other)  # C1
    # a sort change after the move still searches the tag the address shows, and pushes it encoded: written raw, `?tag=a b&c&sort=views` reads back as the tag `a b`
    assert [(query.get("tag"), "q" in query, query.get("sort")) for query in _searches(resorted)] == [(["a b&c"], False, ["views"])], (why, resorted)  # C1
    assert _history(resorted) == [("push", "/search.html", {"tag": ["a b&c"], "sort": ["views"]})], (why, resorted)  # C1
    assert resorted["cards"] == ["peer.example::abcviewed-0", "peer.example::abcviewed-1"], (why, resorted)  # C1
    # a handler that reads tag before q, or keeps the tag mode it was in, sends tag=Linux here
    assert [(query.get("q"), "tag" in query) for query in _searches(mixed)] == [(["music"], False)], (why, mixed)  # C2
    # a handler that never re-runs the mode leaves relevance unselectable and the heading naming a tag no longer searched
    assert mixed["relevance"] == {"hidden": False, "disabled": False} and mixed["heading"]["hidden"] is True, (why, mixed)  # C2
    assert mixed["status"] == "Showing 3 of 8 matched videos.", (why, mixed)  # C2
    # left alone, the address keeps a tag the page is not showing, and a reload or a link copied from it carries the tag on
    assert (urlsplit(mixed["address"]).path, parse_qs(urlsplit(mixed["address"]).query).get("q"), "tag" in parse_qs(urlsplit(mixed["address"]).query)) == ("/search.html", ["music"], False), (why, mixed)  # C2
    # the entry being rewritten is the one navigated to; a push stacks a second one on it and drops the forward history
    assert [kind for kind, _, _ in _history(mixed)] == ["replace"], (why, mixed)  # C2
