"""The video page, run in node with the real page module: "Load more comments" appends the next thread batches from the source instance until the list holds the total, then hides, and a double click sends one request.

- With a first batch of threads 1..20 under a total of 25 and a `start=20` batch of 21..25, the first batch renders 20 threads with "Load more comments" shown. A double click on it (two clicks with no settle between) sends `start=20` exactly once, and the only thread-list requests are `start=0` and `start=20`. The list then holds threads 1..25 in order and the button is hidden.
- With three full batches under a total of 60, one click leaves threads 1..40 with the button still shown and `start=40` not yet requested. A second click requests `start=40` once, and the list then holds threads 1..60 with the button hidden, though that last batch was a full 20.

The runner is the phase 2 harness: it stubs `document` (the comments heading, status and "more" button seeded with video-page.html's own text, the button starting hidden as it does there), `window.location`, the storages, `ResizeObserver`, `getComputedStyle` and `fetch`, which answers `/api/video` with the case's body, the thread list (keyed `threads?start=N`) from the case's `COMMENTS` map, and `{}` elsewhere. It also records each element's `addEventListener` listeners. It runs the case's `STEPS`, each a `{click, nth, times}`: it finds the `nth` node under the four comment roots that has a click listener and reads `click`, and clicks it `times` times back to back. A click reaches the listeners only while the node is neither disabled nor hidden, as for a user. It settles and snapshots the roots after each step.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
TITLE = "Taxonomy fixture title"
HOST = "peer.example"
COMMENT_ROOTS = ["comments-heading", "comments-list", "comments-status", "comments-more"]
LIST = "https://peer.example/api/v1/videos/v1/comment-threads?start={}&count=20&sort=-createdAt"
LOAD_MORE = "Load more comments"
INITIAL_TEXT = {
    match.group(1): html.unescape(match.group(2))
    for match in re.finditer(r'id="(comments-heading|comments-status|comments-more)"[^>]*>([^<]*)<', (FRONTEND / "video-page.html").read_text())
}

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: `?id=v1&host=${process.env.HOST}` },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage, addEventListener() {} };
const text = (value) => ({ nodeType: 3, textContent: String(value) });
const nodes = (items) => items.map((n) => (typeof n === "string" ? text(n) : n));
const markupCalls = [];
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
    insertAdjacentHTML: (position, html) => { markupCalls.push({ el, position, html: String(html) }); }, remove() {},
  };
  return el;
};
const initiallyHidden = JSON.parse(process.env.INITIALLY_HIDDEN);
// The comments heading, status and "more" button start with video-page.html's own text, so a state the page leaves untouched reads as it would in the browser.
const initialText = JSON.parse(process.env.INITIAL_TEXT);
const seeded = (id) => { const el = element("div", initiallyHidden.includes(id)); if (id in initialText) el.textContent = initialText[id]; return el; };
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, seeded(id)); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
// The collapsible description (issue 14) observes and measures the description; nothing here renders, so it measures as empty.
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
const comments = JSON.parse(process.env.COMMENTS ?? "{}");
const requested = [];
const requestedUrls = [];
globalThis.fetch = async (input) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requested.push(url.pathname);
  requestedUrls.push(url.href);
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/video") return new Response(process.env.VIDEO_BODY, { status: 200, headers });
  const key = url.pathname.endsWith("/comment-threads") ? `threads?start=${url.searchParams.get("start")}` : url.pathname;
  const entry = comments[key];
  if (entry === "throw") throw new TypeError("Failed to fetch");
  if (entry === undefined) return new Response("{}", { status: 200, headers });
  return new Response("raw" in entry ? entry.raw : JSON.stringify(entry.body), { status: entry.status ?? 200, headers });
};
const warned = [];
console.warn = (...args) => { warned.push(String(args[0])); };
// A failure that escapes the page would otherwise end node before the report; recorded, it is shown next to the state the page left.
const rejections = [];
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
await import(process.env.BUNDLE);
// Every stubbed fetch resolves at once, so the page's loads, the disabled check included, have settled within a few macrotasks.
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
const walk = (node) => (node == null ? null : node.nodeType !== 1 ? { type: node.nodeType, text: node.textContent } : {
  type: 1, tag: node.tagName, cls: node.className, text: node.textContent, hidden: node.hidden, attrs: { ...node.attrs },
  markup: markupCalls.filter((call) => call.el === node).length, children: node.children.map(walk) });
const roots = JSON.parse(process.env.COMMENT_ROOTS);
const snapshots = [];
const snapshot = () => snapshots.push(Object.fromEntries(roots.map((id) => [id, walk(byId.get(id))])));
// A user cannot click a disabled or unrendered button, so such a click never reaches the listeners; a listener's own throw is kept like a rejection.
const click = (el) => {
  if (el.disabled || el.hidden) return false;
  const event = { type: "click", target: el, currentTarget: el, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() {} };
  for (const listener of [...(el.listeners.click ?? [])]) { try { listener.call(el, event); } catch (error) { rejections.push(String(error)); } }
  return true;
};
const descend = (node) => (node?.nodeType === 1 ? [node, ...node.children.flatMap(descend)] : []);
const clickable = (label) => roots.flatMap((id) => descend(byId.get(id))).filter((node) => (node.listeners.click ?? []).length > 0 && node.textContent.trim() === label);
await settle();
snapshot();
const steps = [];
for (const step of JSON.parse(process.env.STEPS ?? "[]")) {
  const matches = clickable(step.click);
  const target = matches[step.nth ?? 0];
  // The node is found once per step, so every click of a double click lands on the same button whatever text it shows between them.
  const dispatched = [];
  for (let i = 0; i < (step.times ?? 1); i += 1) dispatched.push(target ? click(target) : false);
  await settle();
  // How many requests the page had made by this step's snapshot, so a request is placed before or after each step.
  steps.push({ label: step.click, matches: matches.length, dispatched, requestsSoFar: requestedUrls.length });
  snapshot();
}
const report = (id) => ({ text: byId.get(id)?.textContent ?? null, hidden: byId.get(id)?.hidden ?? null });
// A report past 64 KiB is still being flushed to the pipe when write returns, so node exits only once it has drained.
process.stdout.write(JSON.stringify({ requested, requestedUrls, snapshots, steps, warned, rejections, "video-title": report("video-title") }) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_comments_more")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path, comments: dict, steps: list[dict]) -> dict:
    body = {"videoUuid": "uuid-1", "title": TITLE, "category": "Music", "originalUrl": f"https://{HOST}/videos/watch/uuid-1"}
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "HOST": HOST,
             "VIDEO_BODY": json.dumps(body), "INITIALLY_HIDDEN": json.dumps(["comments-more"]), "INITIAL_TEXT": json.dumps(INITIAL_TEXT),
             "COMMENTS": json.dumps(comments), "COMMENT_ROOTS": json.dumps(COMMENT_ROOTS), "STEPS": json.dumps(steps)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the button was seeded with the real markup's label, the page rendered the /api/video body, and every step left a snapshot
    assert INITIAL_TEXT.get("comments-more") == LOAD_MORE, INITIAL_TEXT
    assert page["video-title"]["text"] == TITLE, page
    assert len(page["snapshots"]) == len(steps) + 1, page["snapshots"]
    return page


def _batch(total: int, ids: range) -> dict:
    return {"body": {"total": total, "data": [
        {"id": i, "threadId": i, "text": f"comment {i}", "createdAt": "2024-01-01T00:00:00.000Z", "isDeleted": False, "totalReplies": 0,
         "account": {"name": f"user{i}", "host": HOST, "displayName": f"User {i}"}}
        for i in ids]}}


def _elements(node: dict | None, cls: str) -> list[dict]:
    found = []
    for child in (node or {}).get("children", []):
        if child["type"] == 1 and cls in child["cls"].split():
            found.append(child)
        found.extend(_elements(child, cls))
    return found


def _bodies(snap: dict) -> list[str]:
    return [body["text"] for thread in _elements(snap["comments-list"], "comment-thread") for body in _elements(thread, "comment-body")]


def _thread_urls(page: dict, upto: int | None = None) -> list[str]:
    return [url for url in page["requestedUrls"][:upto] if "/comment-threads?" in url]


def test_a_double_click_on_load_more_requests_start_20_once_then_the_list_holds_all_25_and_the_button_hides(bundle):
    comments = {"threads?start=0": _batch(25, range(1, 21)), "threads?start=20": _batch(25, range(21, 26))}
    page = _page(bundle, comments, [{"click": LOAD_MORE, "times": 2}])
    first, last = page["snapshots"][0], page["snapshots"][-1]

    # control: before any click the list held threads 1..20 from a start=0 request in the form LIST names, so the list and URL readings below are real
    assert _bodies(first) == [f"comment {i}" for i in range(1, 21)], (first["comments-list"], page["rejections"])
    assert _thread_urls(page)[:1] == [LIST.format(0)], page["requestedUrls"]
    assert page["requestedUrls"].count(LIST.format(20)) == 1, (_thread_urls(page), page["steps"], first["comments-more"])  # C1
    # an offset advanced on each click instead of guarded would send start=20 and start=40, one each
    assert _thread_urls(page) == [LIST.format(0), LIST.format(20)], _thread_urls(page)  # C1
    # the start=20 request came from the click: the button was shown over the first 20, exactly one "Load more comments" carries a click listener, and the first click of the pair reached it
    assert first["comments-more"]["hidden"] is False, (first["comments-more"], page["rejections"])
    assert page["steps"][0]["matches"] == 1 and page["steps"][0]["dispatched"][0] is True, page["steps"]
    assert _bodies(last) == [f"comment {i}" for i in range(1, 26)], (last["comments-list"], page["rejections"])  # C2
    assert last["comments-more"]["hidden"] is True, last["comments-more"]  # C2


def test_load_more_stays_shown_below_the_total_and_hides_once_a_full_last_batch_reaches_it(bundle):
    comments = {"threads?start=0": _batch(60, range(1, 21)), "threads?start=20": _batch(60, range(21, 41)), "threads?start=40": _batch(60, range(41, 61))}
    page = _page(bundle, comments, [{"click": LOAD_MORE}, {"click": LOAD_MORE}])
    first, middle, last = page["snapshots"]

    # control: before any click the list held threads 1..20 from a start=0 request in the form LIST names, so the list and URL readings below are real
    assert _bodies(first) == [f"comment {i}" for i in range(1, 21)], (first["comments-list"], page["rejections"])
    assert _thread_urls(page)[:1] == [LIST.format(0)], page["requestedUrls"]
    # 40 of 60: a page that hides after any extra batch would hide here
    assert _bodies(middle) == [f"comment {i}" for i in range(1, 41)], (middle["comments-list"], page["steps"], first["comments-more"], page["rejections"])  # C2
    assert middle["comments-more"]["hidden"] is False, middle["comments-more"]  # C2
    # the first step found exactly one button and its click reached it
    assert (page["steps"][0]["matches"], page["steps"][0]["dispatched"]) == (1, [True]), page["steps"]
    assert _thread_urls(page, page["steps"][0]["requestsSoFar"]) == [LIST.format(0), LIST.format(20)], _thread_urls(page)  # C2
    # the second click asks from the advanced offset, once
    assert _thread_urls(page) == [LIST.format(0), LIST.format(20), LIST.format(40)], _thread_urls(page)  # C2
    # the last batch is a full 20, so only a count held against the total hides here, where a short-batch rule would keep the button
    assert _bodies(last) == [f"comment {i}" for i in range(1, 61)], (last["comments-list"], page["rejections"])  # C2
    assert last["comments-more"]["hidden"] is True, last["comments-more"]  # C2
