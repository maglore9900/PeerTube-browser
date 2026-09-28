"""The video page, run in node with the real page module: a thread's "Show N replies" toggle fetches the thread's reply tree from the source instance once, even on a double click, shows it under that thread as pre-order reply rows with depth classes, and hides and re-shows it with no further request and no duplicate rows.

- The first batch holds thread 8 with no replies and thread 7 with a `totalReplies` of 4. Before any click no thread-detail request has been made, and the only shown control in the comments is "Show 4 replies".
- Thread 7's detail answers children `[r1 deleted with child r2, r3 deleted with no children, r4]`. A double click on "Show 4 replies" (two clicks with no settle between) requests `https://peer.example/api/v1/videos/v1/comment-threads/7` exactly once. Thread 7 then holds one shown `comment-replies` container whose `comment-reply` rows are, in order: r1 reading "Comment deleted" with no author or body at `comment-depth-1`, r2 with its author and body at `comment-depth-2`, and r4 with its author and body at `comment-depth-1`. r3 is left out. The shown controls hold one "Hide replies" and no "Show 4 replies", and thread 8 holds no reply container or row.
- A click on "Hide replies" hides the container, and the shown controls hold one "Show 4 replies" and no "Hide replies". A click on that shows the container again with the same three rows, once each. Neither click makes a request of any kind, so the detail URL is requested once over the whole run.

The runner is the phase 3 harness: it stubs `document` (the comments heading, status and "more" button seeded with video-page.html's own text, the button starting hidden as it does there), `window.location`, the storages, `ResizeObserver`, `getComputedStyle` and `fetch`, which answers `/api/video` with the case's body, the thread list (keyed `threads?start=N`) and any other path from the case's `COMMENTS` map, and `{}` elsewhere. It records each element's `addEventListener` listeners and runs the case's `STEPS`, each a `{click, times}`: it finds the node under the four comment roots that has a click listener and reads `click`, and clicks it `times` times back to back. A click reaches the listeners only while the node is neither disabled nor hidden, as for a user. It settles and snapshots the roots after each step. It also reports the request count at the first snapshot, and with each snapshot the labels of the shown controls: the nodes under the four roots that carry a click listener and have no hidden node on their path.
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
DETAIL = "https://peer.example/api/v1/videos/v1/comment-threads/7"
SHOW = "Show 4 replies"
HIDE = "Hide replies"
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
// The labels a user can see and click: a listener-bearing node counts only while neither it nor any node above it is hidden.
const shownControls = () => {
  const labels = [];
  const visit = (node, hiddenAbove) => {
    if (node?.nodeType !== 1) return;
    const hidden = hiddenAbove || node.hidden;
    if (!hidden && (node.listeners.click ?? []).length > 0) labels.push(node.textContent.trim());
    node.children.forEach((child) => visit(child, hidden));
  };
  roots.forEach((id) => visit(byId.get(id), false));
  return labels;
};
const snapshots = [];
const controls = [];
const snapshot = () => { snapshots.push(Object.fromEntries(roots.map((id) => [id, walk(byId.get(id))]))); controls.push(shownControls()); };
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
// How many requests the page had made before any step, so a request is placed before or after the first click.
const startRequests = requestedUrls.length;
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
process.stdout.write(JSON.stringify({ requested, requestedUrls, startRequests, snapshots, controls, steps, warned, rejections, "video-title": report("video-title") }) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_comments_replies")
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
    # control: the page rendered the /api/video body, and every step left a snapshot and a control reading
    assert page["video-title"]["text"] == TITLE, page
    assert len(page["snapshots"]) == len(page["controls"]) == len(steps) + 1, page["snapshots"]
    return page


def _comment(comment_id: int, thread_id: int, text: str, author: str | None, *, deleted: bool = False, replies: int = 0) -> dict:
    # A deleted PeerTube comment arrives with empty text and no account.
    account = None if author is None else {"name": author.lower(), "host": HOST, "displayName": author}
    return {"id": comment_id, "threadId": thread_id, "text": text, "createdAt": "2024-01-01T00:00:00.000Z", "isDeleted": deleted, "totalReplies": replies, "account": account}


THREADS = {"body": {"total": 2, "data": [_comment(8, 8, "a thread nobody answered", "Nora"), _comment(7, 7, "a thread with replies", "Tess", replies=4)]}}
TREE = {"body": {"comment": _comment(7, 7, "a thread with replies", "Tess", replies=4), "children": [
    {"comment": _comment(71, 7, "", None, deleted=True), "children": [{"comment": _comment(72, 7, "an answer under the deleted reply", "Rita"), "children": []}]},
    {"comment": _comment(73, 7, "", None, deleted=True), "children": []},
    {"comment": _comment(74, 7, "a later direct reply", "Ravi"), "children": []},
]}}
# (depth classes, authors, bodies) per `comment-reply` row, in order: r1 deleted with a child, r2 under it, r4; the deleted leaf r3 has no row
ROWS = [
    (["comment-depth-1"], [], []),
    (["comment-depth-2"], ["Rita"], ["an answer under the deleted reply"]),
    (["comment-depth-1"], ["Ravi"], ["a later direct reply"]),
]


def _elements(node: dict | None, cls: str) -> list[dict]:
    found = []
    for child in (node or {}).get("children", []):
        if child["type"] == 1 and cls in child["cls"].split():
            found.append(child)
        found.extend(_elements(child, cls))
    return found


def _texts(node: dict, cls: str) -> list[str]:
    return [found["text"] for found in _elements(node, cls)]


def _rows(container: dict) -> list[tuple]:
    return [([c for c in row["cls"].split() if c.startswith("comment-depth-")], _texts(row, "comment-author"), _texts(row, "comment-body")) for row in _elements(container, "comment-reply")]


def test_a_double_clicked_reply_toggle_fetches_the_tree_once_shows_pre_order_depth_rows_and_hides_and_reshows_them_without_a_request(bundle):
    page = _page(bundle, {"threads?start=0": THREADS, "/api/v1/videos/v1/comment-threads/7": TREE}, [{"click": SHOW, "times": 2}, {"click": HIDE}, {"click": SHOW}])
    first, expanded, collapsed, reshown = page["snapshots"]
    steps = page["steps"]

    # control: before any click both threads rendered from the first batch and no thread-detail request had been made, so a detail request below came from a click
    assert [_texts(thread, "comment-body") for thread in _elements(first["comments-list"], "comment-thread")] == [["a thread nobody answered"], ["a thread with replies"]], (first["comments-list"], page["rejections"])
    assert DETAIL not in page["requestedUrls"][:page["startRequests"]], page["requestedUrls"]
    # a toggle with no in-flight guard sends the detail request twice for the two clicks
    assert page["requestedUrls"][:steps[0]["requestsSoFar"]].count(DETAIL) == 1, (page["requestedUrls"], steps, page["controls"][0], page["rejections"])  # C1
    # the toggle was the only shown control, labelled from totalReplies (4) and not from the 3 rows it will show; thread 8, with no replies, has none; the first click of the pair reached it
    assert page["controls"][0] == [SHOW], page["controls"][0]  # C1
    assert steps[0]["matches"] == 1 and steps[0]["dispatched"][0] is True, steps  # C1
    other, thread = _elements(expanded["comments-list"], "comment-thread")
    containers = _elements(thread, "comment-replies")
    assert [container["hidden"] for container in containers] == [False], (thread, page["rejections"])  # C1
    # pre-order: breadth-first gives r1, r4, r2; post-order gives r2 first; a flat or zero-based depth gives other classes; rendering every deleted reply adds r3 as a fourth row; dropping every deleted reply loses r1
    assert _rows(containers[0]) == ROWS, containers[0]  # C1
    assert _elements(containers[0], "comment-reply")[0]["text"] == "Comment deleted", containers[0]  # C1
    assert page["controls"][1].count(HIDE) == 1 and SHOW not in page["controls"][1], page["controls"][1]  # C1
    assert _elements(other, "comment-replies") == [] and _elements(other, "comment-reply") == [], other  # C1
    # hiding: the click reached "Hide replies", the container hid, and the label went back to the total, not to the 3 rows shown
    assert (steps[1]["matches"], steps[1]["dispatched"]) == (1, [True]), steps  # C2
    assert [container["hidden"] for container in _elements(_elements(collapsed["comments-list"], "comment-thread")[1], "comment-replies")] == [True], collapsed["comments-list"]  # C2
    assert page["controls"][2].count(SHOW) == 1 and HIDE not in page["controls"][2], page["controls"][2]  # C2
    # re-showing: the same three rows once each, where appending the tree again on each show holds six
    assert (steps[2]["matches"], steps[2]["dispatched"]) == (1, [True]), steps  # C2
    containers = _elements(_elements(reshown["comments-list"], "comment-thread")[1], "comment-replies")
    assert [container["hidden"] for container in containers] == [False], reshown["comments-list"]  # C2
    assert _rows(containers[0]) == ROWS, containers[0]  # C2
    # no request of any kind after the first step, and the detail URL once over the whole run
    assert steps[2]["requestsSoFar"] == steps[0]["requestsSoFar"], (page["requestedUrls"][steps[0]["requestsSoFar"]:], steps)  # C2
    assert page["requestedUrls"].count(DETAIL) == 1, page["requestedUrls"]  # C2
