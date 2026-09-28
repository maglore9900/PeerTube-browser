"""The video page, run in node with the real page module: a first comments batch that is empty or fails ends in a defined state inside the comments section, and the taxonomy block still renders.

- An empty first batch (`{total: 0, data: []}`) whose video answers `/api/v1/videos/v1` with `commentsEnabled: true`, with `commentsPolicy.id` 3, or with a 500 makes that request and reads "No comments yet." under "Comments (0)".
- An empty first batch whose video answers `commentsEnabled: false` or `commentsPolicy.id` 2 (the disabled value the plan provisionally takes for R3) makes that request, reads "Comments are unavailable on peer.example." with one link to `https://peer.example/videos/watch/uuid-1`, keeps the heading "Comments", and shows the category "Music".
- A first thread-list request that throws, answers 500, or answers unparsable JSON, on a video from other.example, reads "Comments are unavailable on other.example." with one link to `https://other.example/videos/watch/uuid-1` (the body's `originalUrl`, read after the page settles), shows the category "Music", and logs exactly one `console.warn` whose first argument starts with "[comments]".

The runner is the phase 1 harness: it stubs `document` (the comments heading and status seeded with video-page.html's own text), `window.location`, the storages, `ResizeObserver`, `getComputedStyle` and `fetch`, which answers `/api/video` with the case's body, the thread list (keyed `threads?start=N`) and other paths from the case's `COMMENTS` map, and `{}` elsewhere. It also records `console.warn` first arguments, records unhandled rejections so a failure that escapes the page cannot end node before the report, and reports the page's own `#original-link` href.
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
COMMENT_ROOTS = ["comments-heading", "comments-list", "comments-status", "comments-more"]
VIDEO_PATH = "/api/v1/videos/v1"
EMPTY_BATCH = {"body": {"total": 0, "data": []}}
# The failed-batch cases run on a second host, so a host or href fixed in the page cannot pass both tests.
HOST = "peer.example"
OTHER_HOST = "other.example"
INITIAL_TEXT = {
    match.group(1): html.unescape(match.group(2))
    for match in re.finditer(r'id="(comments-heading|comments-status)"[^>]*>([^<]*)<', (FRONTEND / "video-page.html").read_text())
}


def _first_page_url(host: str) -> str:
    return f"https://{host}/api/v1/videos/v1/comment-threads?start=0&count=20&sort=-createdAt"


def _original(host: str) -> str:
    return f"https://{host}/videos/watch/uuid-1"


def _unavailable(host: str) -> str:
    return f"Comments are unavailable on {host}."

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
    nodeType: 1, tagName: tag.toUpperCase(), hidden, children: [], dataset: {}, style: {}, attrs: {}, parentElement: null,
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
    setAttribute: (name, value) => { if (name === "hidden") el.hidden = true; else if (name === "class") el.className = value; else el.attrs[name] = String(value); },
    removeAttribute: (name) => { if (name === "hidden") el.hidden = false; else delete el.attrs[name]; },
    toggleAttribute: (name, force) => { const on = force ?? !(name === "hidden" ? el.hidden : name in el.attrs); el[on ? "setAttribute" : "removeAttribute"](name, ""); return on; },
    getAttribute: (name) => (name === "hidden" ? (el.hidden ? "" : null) : el.attrs[name] ?? null),
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, insertAdjacentHTML: (position, html) => { markupCalls.push({ el, position, html: String(html) }); }, remove() {},
  };
  return el;
};
const initiallyHidden = JSON.parse(process.env.INITIALLY_HIDDEN);
// The comments heading and status start with video-page.html's own text, so a state the page leaves untouched reads as it would in the browser.
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
const snapshots = [];
const snapshot = () => snapshots.push(Object.fromEntries(JSON.parse(process.env.COMMENT_ROOTS).map((id) => [id, walk(byId.get(id))])));
await settle();
snapshot();
const report = (id) => ({ text: byId.get(id)?.textContent ?? null, hidden: byId.get(id)?.hidden ?? null });
const ids = ["video-title", "video-category", "video-category-value"];
const originalHref = byId.get("original-link")?.attrs.href ?? null;
process.stdout.write(JSON.stringify({ requested, requestedUrls, snapshots, warned, rejections, originalHref, ...Object.fromEntries(ids.map((id) => [id, report(id)])) }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_comments_states")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path, comments: dict, host: str = HOST) -> dict:
    body = {"videoUuid": "uuid-1", "title": TITLE, "category": "Music", "originalUrl": _original(host)}
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "HOST": host,
             "VIDEO_BODY": json.dumps(body), "INITIALLY_HIDDEN": json.dumps([]), "INITIAL_TEXT": json.dumps(INITIAL_TEXT),
             "COMMENTS": json.dumps(comments), "COMMENT_ROOTS": json.dumps(COMMENT_ROOTS)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the heading and status were seeded from the real markup, the page rendered the /api/video body and asked for the first batch, so the state below follows that batch
    assert set(INITIAL_TEXT) == {"comments-heading", "comments-status"}, INITIAL_TEXT
    assert page["video-title"]["text"] == TITLE, page
    assert _first_page_url(host) in page["requestedUrls"], page["requestedUrls"]
    return page


def _links(status: dict) -> list[dict]:
    return [child for child in status["children"] if child["type"] == 1 and child["tag"] == "A"]


@pytest.mark.parametrize("video_answer", [
    {"body": {"commentsEnabled": True}},
    # 3 sits next to the disabled 2 in PeerTube's policy enum, so only a comparison against 2 itself reads it as enabled
    {"body": {"commentsPolicy": {"id": 3}}},
    {"status": 500},
], ids=["commentsEnabled-true", "commentsPolicy-3", "video-500"])
def test_an_empty_first_batch_on_a_video_not_reporting_comments_disabled_reads_no_comments_yet_under_comments_0(bundle, video_answer):
    page = _page(bundle, {"threads?start=0": EMPTY_BATCH, VIDEO_PATH: video_answer})
    snap = page["snapshots"][-1]

    assert VIDEO_PATH in page["requested"], page["requested"]  # C1
    assert snap["comments-status"]["text"] == "No comments yet.", (snap["comments-status"], page["rejections"])  # C1
    assert snap["comments-heading"]["text"] == "Comments (0)", snap["comments-heading"]  # C1


@pytest.mark.parametrize("video_body", [
    {"commentsEnabled": False},
    {"commentsPolicy": {"id": 2, "label": "Disabled"}},
], ids=["commentsEnabled-false", "commentsPolicy-2"])
def test_an_empty_first_batch_on_a_video_reporting_comments_disabled_shows_the_unavailable_state_and_keeps_the_taxonomy(bundle, video_body):
    page = _page(bundle, {"threads?start=0": EMPTY_BATCH, VIDEO_PATH: {"body": video_body}})
    snap = page["snapshots"][-1]
    status = snap["comments-status"]
    links = _links(status)

    assert VIDEO_PATH in page["requested"], page["requested"]  # C1
    assert status["text"].startswith(_unavailable(HOST)), (status, page["rejections"])  # C1
    assert [link["attrs"].get("href") for link in links] == [_original(HOST)], status  # C1
    # "Comments (0)" would claim an empty discussion the video does not have
    assert snap["comments-heading"]["text"] == "Comments", snap["comments-heading"]  # C1
    assert page["video-category-value"]["text"] == "Music", page  # C1


@pytest.mark.parametrize("first_batch", ["throw", {"status": 500}, {"raw": "not json"}], ids=["throw", "status-500", "raw-not-json"])
def test_a_failed_first_batch_shows_the_unavailable_state_with_the_original_href_keeps_the_taxonomy_and_warns_once(bundle, first_batch):
    page = _page(bundle, {"threads?start=0": first_batch}, OTHER_HOST)
    snap = page["snapshots"][-1]
    status = snap["comments-status"]
    links = _links(status)

    # control: the page's own #original-link carries the body's originalUrl after the settle, so the comments link can be held to it
    assert page["originalHref"] == _original(OTHER_HOST), page["originalHref"]
    assert status["text"].startswith(_unavailable(OTHER_HOST)), (status, page["rejections"])  # C2
    assert [link["attrs"].get("href") for link in links] == [_original(OTHER_HOST)], status  # C2
    assert page["video-category-value"]["text"] == "Music", page  # C2
    assert len([message for message in page["warned"] if message.startswith("[comments]")]) == 1, page["warned"]  # C2
