"""The video page, run in node with the real page module: its taxonomy block shows `/api/video`'s category, language and tags as text, and its comments section shows the source instance's comment threads as text, with defined empty, disabled and failed states, "Load more comments" paging and per-thread reply trees.

Taxonomy:
- For a body with a category, a language and two tags, the category and language items are shown with the body's values, and the tag list holds one `tag-chip` per tag, in order, whose text is the tag.
- For a body with an empty category, language and tag list, the category and language items are hidden and the tag list's only child reads "No tags".
- For a body with a category, an empty language and one tag, only the language item is hidden and the tag list holds one chip.

First batch:
- By the time the page module's import has resolved, before any timer tick, the page has requested `comment-threads?start=0&count=20&sort=-createdAt` from the video's host. For a first page with a total of 3 holding two live threads around a deleted thread with no replies, the heading reads "Comments (3)" and the list holds one `comment-thread` for each live thread, in order. Each thread holds exactly one author (the display name), one `@name@host` handle built from the account's own host (one account is on a host other than the video's), one relative time and one body with its line break kept. The "more" control is hidden and the status is empty.
- For a first page of two threads under a total of 57, the heading reads "Comments (57)". A display name shaped like an `<img onerror>` tag reads literally. A federated HTML body with an encoded `<script>`, a raw `<script>` and a `<b onclick>` reads as its plain text. A body that is not HTML-shaped (markdown, a spaced `< b >` and an `&amp;` entity, which HTML reduction would strip and decode) reads raw. No node under the heading, list, status or "more" control is markup set through innerHTML, and none received insertAdjacentHTML.

Empty and failed first batch:
- An empty first batch (`{total: 0, data: []}`) whose video answers `/api/v1/videos/v1` with `commentsEnabled: true`, with `commentsPolicy.id` 3, or with a 500 makes that request and reads "No comments yet." under "Comments (0)".
- An empty first batch whose video answers `commentsEnabled: false` or `commentsPolicy.id` 2 (the page's `COMMENTS_POLICY_DISABLED`, not yet confirmed against a live instance) makes that request, reads "Comments are unavailable on peer.example." with one link to `https://peer.example/videos/watch/uuid-1`, keeps the heading "Comments", and shows the category "Music".
- A first thread-list request that throws, answers 500, or answers unparsable JSON, on a video from other.example, reads "Comments are unavailable on other.example." with one link to `https://other.example/videos/watch/uuid-1` (the body's `originalUrl`, read after the page settles), shows the category "Music", and logs exactly one `console.warn` whose first argument starts with "[comments]".

Load more:
- With a first batch of threads 1..20 under a total of 25 and a `start=20` batch of 21..25, the first batch renders 20 threads with "Load more comments" shown. A double click on it (two clicks with no settle between) sends `start=20` exactly once, and the only thread-list requests are `start=0` and `start=20`. The list then holds threads 1..25 in order and the button is hidden.
- With three full batches under a total of 60, one click leaves threads 1..40 with the button still shown and `start=40` not yet requested. A second click requests `start=40` once, and the list then holds threads 1..60 with the button hidden, though that last batch was a full 20.

Replies:
- The first batch holds thread 8 with no replies and thread 7 with a `totalReplies` of 4. Before any click no thread-detail request has been made, and the only shown control in the comments is "Show 4 replies".
- Thread 7's detail answers children `[r1 deleted with child r2, r3 deleted with no children, r4]`. A double click on "Show 4 replies" requests `https://peer.example/api/v1/videos/v1/comment-threads/7` exactly once. Thread 7 then holds one shown `comment-replies` container whose `comment-reply` rows are, in order: r1 reading "Comment deleted" with no author or body at `comment-depth-1`, r2 with its author and body at `comment-depth-2`, and r4 with its author and body at `comment-depth-1`. r3 is left out. The shown controls hold one "Hide replies" and no "Show 4 replies", and thread 8 holds no reply container or row.
- A click on "Hide replies" hides the container, and the shown controls hold one "Show 4 replies" and no "Hide replies". A click on that shows the container again with the same three rows, once each. Neither click makes a request of any kind, so the detail URL is requested once over the whole run.

The runner stubs the browser platform node lacks: a `document` of recording elements (the comments heading, status and "more" button seeded with video-page.html's own text), `window.location`, the storages, `ResizeObserver` and `getComputedStyle` for the collapsible description, and `fetch`. `fetch` answers `/api/video` with the case's body, the thread list (keyed `threads?start=N`) and other paths (keyed by pathname) from the case's `COMMENTS` map, and `{}` for unmapped paths. Elements the case names start hidden, so the page has to set their visibility. innerHTML leaves an opaque type-0 node and insertAdjacentHTML is counted per element, so markup cannot pass for text; the runner reports which page elements each detector caught, so a clean comments walk is shown to come from detectors that fire. It records `console.warn` first arguments, unhandled rejections, and each element's click listeners, and runs the case's `STEPS`, each a `{click, nth, times}`: it finds the `nth` node under the four comment roots that has a click listener and reads `click`, and clicks it `times` times back to back. A click reaches the listeners only while the node is neither disabled nor hidden, as for a user. It settles and snapshots the roots, with the labels of the shown controls, before the first step and after each.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
TITLE = "Taxonomy fixture title"
ITEMS = ["video-category", "video-language"]
HOST = "peer.example"
# The failed-batch cases run on a second host, so a host or href fixed in the page cannot pass both.
OTHER_HOST = "other.example"
COMMENT_ROOTS = ["comments-heading", "comments-list", "comments-status", "comments-more"]
VIDEO_PATH = "/api/v1/videos/v1"
DETAIL = "https://peer.example/api/v1/videos/v1/comment-threads/7"
EMPTY_BATCH = {"body": {"total": 0, "data": []}}
LOAD_MORE = "Load more comments"
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
// Only what the page asked for by the time its import resolved, before any timer tick: a request chained behind another load's response is not here yet.
const startUrls = [...requestedUrls];
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
const ids = ["video-title", "video-category", "video-category-value", "video-language", "video-language-value"];
const tags = (byId.get("video-tags")?.children ?? []).map((c) => ({ text: c.textContent, chip: c.nodeType === 1 && c.classList.contains("tag-chip") }));
// Which page elements the detectors caught markup on, so a clean comments walk is shown to come from detectors that do fire.
const idOf = (node) => [...byId.entries()].find(([, el]) => el === node)?.[0] ?? null;
const markupIds = markupCalls.map((call) => idOf(call.el));
const opaqueIds = [...byId.entries()].filter(([, el]) => el.children.some((c) => c.nodeType === 0)).map(([id]) => id);
const originalHref = byId.get("original-link")?.attrs.href ?? null;
// A report past 64 KiB is still being flushed to the pipe when write returns, so node exits only once it has drained.
process.stdout.write(JSON.stringify({ requested, requestedUrls, startUrls, startRequests, snapshots, controls, steps, warned, rejections, markupIds, opaqueIds, originalHref,
  ...Object.fromEntries(ids.map((id) => [id, report(id)])), tags }) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_page")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path, body: dict, *, initially_hidden: list[str] = (), comments: dict | None = None, steps: list[dict] = (), host: str = HOST) -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "HOST": host,
             "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, **body}), "INITIALLY_HIDDEN": json.dumps(list(initially_hidden)),
             "INITIAL_TEXT": json.dumps(INITIAL_TEXT), "COMMENTS": json.dumps(comments or {}), "COMMENT_ROOTS": json.dumps(COMMENT_ROOTS),
             "STEPS": json.dumps(list(steps))},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page asked /api/video and rendered its body, and every step left a snapshot and a control reading
    assert "/api/video" in page["requested"], page
    assert page["video-title"]["text"] == TITLE, page
    assert len(page["snapshots"]) == len(page["controls"]) == len(steps) + 1, page["snapshots"]
    return page


def _list_url(start: int, host: str = HOST) -> str:
    return f"https://{host}/api/v1/videos/v1/comment-threads?start={start}&count=20&sort=-createdAt"


def _original(host: str) -> str:
    return f"https://{host}/videos/watch/uuid-1"


def _unavailable(host: str) -> str:
    return f"Comments are unavailable on {host}."


def _music(host: str = HOST) -> dict:
    return {"category": "Music", "originalUrl": _original(host)}


def _created(ago: timedelta) -> str:
    return (datetime.now(timezone.utc) - ago).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _thread(thread_id: int, name: str, display_name: str, text: str, ago: timedelta, host: str = HOST) -> dict:
    return {"id": thread_id, "threadId": thread_id, "text": text, "createdAt": _created(ago), "isDeleted": False, "totalReplies": 0,
            "account": {"name": name, "host": host, "displayName": display_name}}


def _comment(comment_id: int, thread_id: int, text: str, author: str | None, *, deleted: bool = False, replies: int = 0) -> dict:
    # A deleted PeerTube comment arrives with empty text and no account.
    account = None if author is None else {"name": author.lower(), "host": HOST, "displayName": author}
    return {"id": comment_id, "threadId": thread_id, "text": text, "createdAt": "2024-01-01T00:00:00.000Z", "isDeleted": deleted, "totalReplies": replies, "account": account}


def _batch(total: int, ids: range) -> dict:
    return {"body": {"total": total, "data": [_comment(i, i, f"comment {i}", f"User{i}") for i in ids]}}


def _elements(node: dict | None, cls: str) -> list[dict]:
    found = []
    for child in (node or {}).get("children", []):
        if child["type"] == 1 and cls in child["cls"].split():
            found.append(child)
        found.extend(_elements(child, cls))
    return found


def _texts(node: dict, cls: str) -> list[str]:
    return [found["text"] for found in _elements(node, cls)]


def _field(threads: list[dict], cls: str) -> list[list[str]]:
    return [_texts(thread, cls) for thread in threads]


def _all_nodes(node: dict | None) -> list[dict]:
    if node is None:
        return []
    return [node, *(n for child in node.get("children", []) for n in _all_nodes(child))]


def _links(status: dict) -> list[dict]:
    return [child for child in status["children"] if child["type"] == 1 and child["tag"] == "A"]


def _bodies(snap: dict) -> list[str]:
    return [body for thread in _elements(snap["comments-list"], "comment-thread") for body in _texts(thread, "comment-body")]


def _thread_urls(page: dict, upto: int | None = None) -> list[str]:
    return [url for url in page["requestedUrls"][:upto] if "/comment-threads?" in url]


def _rows(container: dict) -> list[tuple]:
    return [([c for c in row["cls"].split() if c.startswith("comment-depth-")], _texts(row, "comment-author"), _texts(row, "comment-body")) for row in _elements(container, "comment-reply")]


def test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag(bundle):
    page = _page(bundle, {"category": "Science & Technology", "language": "English", "tags": ["alpha", "beta"]}, initially_hidden=ITEMS)

    assert page["video-category"]["hidden"] is False, page
    assert page["video-category-value"]["text"] == "Science & Technology", page
    assert page["video-language"]["hidden"] is False, page
    assert page["video-language-value"]["text"] == "English", page
    assert page["tags"] == [{"text": "alpha", "chip": True}, {"text": "beta", "chip": True}], page


def test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags(bundle):
    page = _page(bundle, {"category": "", "language": "", "tags": []})

    assert page["video-category"]["hidden"] is True, page
    assert page["video-language"]["hidden"] is True, page
    assert [child["text"] for child in page["tags"]] == ["No tags"], page


def test_an_empty_language_alone_hides_only_the_language_item(bundle):
    page = _page(bundle, {"category": "Music", "language": "", "tags": ["solo"]}, initially_hidden=["video-category"])

    assert page["video-category"]["hidden"] is False, page
    assert page["video-category-value"]["text"] == "Music", page
    assert page["video-language"]["hidden"] is True, page
    assert page["tags"] == [{"text": "solo", "chip": True}], page


def test_the_first_page_is_requested_at_start_and_renders_one_text_thread_per_live_thread_under_the_total_heading(bundle):
    deleted = {"id": 2, "threadId": 2, "text": "", "createdAt": _created(timedelta(days=1)), "isDeleted": True, "totalReplies": 0, "account": None}
    first_page = {"total": 3, "data": [
        _thread(1, "alice", "Alice", "line one\nline two", timedelta(hours=3, minutes=20)),
        deleted,
        _thread(3, "bob", "Bob", "hi from bob", timedelta(days=2, hours=5), host="tube.other.example"),
    ]}
    # "more" starts shown, so only the page hiding it can leave it hidden
    page = _page(bundle, {}, comments={"threads?start=0": {"body": first_page}})
    snap = page["snapshots"][-1]
    threads = _elements(snap["comments-list"], "comment-thread")

    # control: the page's own first fetch is in the start record, so an empty record would mean the capture was broken rather than the comments late
    assert f"{BASE}/api/video?id=v1&host=peer.example" in page["startUrls"], page["startUrls"]
    assert _list_url(0) in page["startUrls"], page["startUrls"]
    assert _list_url(0) in page["requestedUrls"], page["requestedUrls"]
    assert snap["comments-heading"]["text"] == "Comments (3)", snap["comments-heading"]
    assert len(threads) == 2, snap["comments-list"]
    assert _field(threads, "comment-author") == [["Alice"], ["Bob"]], threads
    # bob's account is on a host other than the video's, so only a handle built from account.host reads right
    assert _field(threads, "comment-handle") == [["@alice@peer.example"], ["@bob@tube.other.example"]], threads
    assert _field(threads, "comment-body") == [["line one\nline two"], ["hi from bob"]], threads
    assert _field(threads, "comment-time") == [["3 hours ago"], ["2 days ago"]], threads
    assert snap["comments-more"]["hidden"] is True, snap["comments-more"]
    assert snap["comments-status"]["text"] == "", snap["comments-status"]


def test_hostile_names_and_federated_html_reach_the_comments_only_as_text(bundle):
    hostile_name = "<img src=x onerror=alert(1)>"
    federated = '&lt;script&gt;alert(1)&lt;/script&gt;<script>alert(2)</script><b onclick="alert(3)">bold</b>'
    first_page = {"total": 57, "data": [
        _thread(1, "mallory", hostile_name, federated, timedelta(hours=1)),
        # not HTML-shaped (no `<` before a letter or `/`), yet HTML reduction would strip `< b >` and decode `&amp;`, so raw and reduced read differently
        _thread(2, "carol", "Carol", "**bold** a < b > c &amp; d", timedelta(hours=2)),
    ]}
    page = _page(bundle, {}, comments={"threads?start=0": {"body": first_page}})
    snap = page["snapshots"][-1]
    threads = _elements(snap["comments-list"], "comment-thread")
    every_node = [node for root in COMMENT_ROOTS for node in _all_nodes(snap[root])]

    # control: both detectors fire on the page's own markup outside the comments, so an empty count below is not a dead detector
    assert "like-button" in page["markupIds"], page["markupIds"]
    assert "similar-videos" in page["opaqueIds"], page["opaqueIds"]
    # both threads rendered with their authors as text, which also arms the two absence checks below with real comment nodes
    assert _field(threads, "comment-author") == [[hostile_name], ["Carol"]], threads
    # 57 in total, two rows on this page: only a heading read from `total` gives 57, where the page's row count and the shown threads both give 2
    assert snap["comments-heading"]["text"] == "Comments (57)", snap["comments-heading"]
    assert _field(threads, "comment-body") == [["<script>alert(1)</script>alert(2)bold"], ["**bold** a < b > c &amp; d"]], threads
    assert [node for node in every_node if node["type"] == 0] == [], every_node
    assert sum(node.get("markup", 0) for node in every_node) == 0, every_node


def _state_page(bundle: Path, comments: dict, host: str = HOST) -> dict:
    page = _page(bundle, _music(host), comments=comments, host=host)
    # control: the heading and status were seeded from the real markup and the page asked for the first batch, so the state below follows that batch
    assert {"comments-heading", "comments-status"} <= set(INITIAL_TEXT), INITIAL_TEXT
    assert _list_url(0, host) in page["requestedUrls"], page["requestedUrls"]
    return page


@pytest.mark.parametrize("video_answer", [
    {"body": {"commentsEnabled": True}},
    # 3 sits next to the disabled 2 in PeerTube's policy enum, so only a comparison against 2 itself reads it as enabled
    {"body": {"commentsPolicy": {"id": 3}}},
    {"status": 500},
], ids=["commentsEnabled-true", "commentsPolicy-3", "video-500"])
def test_an_empty_first_batch_on_a_video_not_reporting_comments_disabled_reads_no_comments_yet_under_comments_0(bundle, video_answer):
    page = _state_page(bundle, {"threads?start=0": EMPTY_BATCH, VIDEO_PATH: video_answer})
    snap = page["snapshots"][-1]

    assert VIDEO_PATH in page["requested"], page["requested"]
    assert snap["comments-status"]["text"] == "No comments yet.", (snap["comments-status"], page["rejections"])
    assert snap["comments-heading"]["text"] == "Comments (0)", snap["comments-heading"]


@pytest.mark.parametrize("video_body", [
    {"commentsEnabled": False},
    {"commentsPolicy": {"id": 2, "label": "Disabled"}},
], ids=["commentsEnabled-false", "commentsPolicy-2"])
def test_an_empty_first_batch_on_a_video_reporting_comments_disabled_shows_the_unavailable_state_and_keeps_the_taxonomy(bundle, video_body):
    page = _state_page(bundle, {"threads?start=0": EMPTY_BATCH, VIDEO_PATH: {"body": video_body}})
    snap = page["snapshots"][-1]
    status = snap["comments-status"]
    links = _links(status)

    assert VIDEO_PATH in page["requested"], page["requested"]
    assert status["text"].startswith(_unavailable(HOST)), (status, page["rejections"])
    assert [link["attrs"].get("href") for link in links] == [_original(HOST)], status
    # "Comments (0)" would claim an empty discussion the video does not have
    assert snap["comments-heading"]["text"] == "Comments", snap["comments-heading"]
    assert page["video-category-value"]["text"] == "Music", page


@pytest.mark.parametrize("first_batch", ["throw", {"status": 500}, {"raw": "not json"}], ids=["throw", "status-500", "raw-not-json"])
def test_a_failed_first_batch_shows_the_unavailable_state_with_the_original_href_keeps_the_taxonomy_and_warns_once(bundle, first_batch):
    page = _state_page(bundle, {"threads?start=0": first_batch}, OTHER_HOST)
    snap = page["snapshots"][-1]
    status = snap["comments-status"]
    links = _links(status)

    # control: the page's own #original-link carries the body's originalUrl after the settle, so the comments link can be held to it
    assert page["originalHref"] == _original(OTHER_HOST), page["originalHref"]
    assert status["text"].startswith(_unavailable(OTHER_HOST)), (status, page["rejections"])
    assert [link["attrs"].get("href") for link in links] == [_original(OTHER_HOST)], status
    assert page["video-category-value"]["text"] == "Music", page
    assert len([message for message in page["warned"] if message.startswith("[comments]")]) == 1, page["warned"]


def test_a_double_click_on_load_more_requests_start_20_once_then_the_list_holds_all_25_and_the_button_hides(bundle):
    comments = {"threads?start=0": _batch(25, range(1, 21)), "threads?start=20": _batch(25, range(21, 26))}
    page = _page(bundle, _music(), initially_hidden=["comments-more"], comments=comments, steps=[{"click": LOAD_MORE, "times": 2}])
    first, last = page["snapshots"][0], page["snapshots"][-1]

    # control: the button was seeded with the real markup's label, and before any click the list held threads 1..20 from a start=0 request, so the list and URL readings below are real
    assert INITIAL_TEXT.get("comments-more") == LOAD_MORE, INITIAL_TEXT
    assert _bodies(first) == [f"comment {i}" for i in range(1, 21)], (first["comments-list"], page["rejections"])
    assert _thread_urls(page)[:1] == [_list_url(0)], page["requestedUrls"]
    assert page["requestedUrls"].count(_list_url(20)) == 1, (_thread_urls(page), page["steps"], first["comments-more"])
    # an offset advanced on each click instead of guarded would send start=20 and start=40, one each
    assert _thread_urls(page) == [_list_url(0), _list_url(20)], _thread_urls(page)
    # the start=20 request came from the click: the button was shown over the first 20, exactly one "Load more comments" carries a click listener, and the first click of the pair reached it
    assert first["comments-more"]["hidden"] is False, (first["comments-more"], page["rejections"])
    assert page["steps"][0]["matches"] == 1 and page["steps"][0]["dispatched"][0] is True, page["steps"]
    assert _bodies(last) == [f"comment {i}" for i in range(1, 26)], (last["comments-list"], page["rejections"])
    assert last["comments-more"]["hidden"] is True, last["comments-more"]


def test_load_more_stays_shown_below_the_total_and_hides_once_a_full_last_batch_reaches_it(bundle):
    comments = {"threads?start=0": _batch(60, range(1, 21)), "threads?start=20": _batch(60, range(21, 41)), "threads?start=40": _batch(60, range(41, 61))}
    page = _page(bundle, _music(), initially_hidden=["comments-more"], comments=comments, steps=[{"click": LOAD_MORE}, {"click": LOAD_MORE}])
    first, middle, last = page["snapshots"]

    # control: before any click the list held threads 1..20 from a start=0 request, so the list and URL readings below are real
    assert _bodies(first) == [f"comment {i}" for i in range(1, 21)], (first["comments-list"], page["rejections"])
    assert _thread_urls(page)[:1] == [_list_url(0)], page["requestedUrls"]
    # 40 of 60: a page that hides after any extra batch would hide here
    assert _bodies(middle) == [f"comment {i}" for i in range(1, 41)], (middle["comments-list"], page["steps"], first["comments-more"], page["rejections"])
    assert middle["comments-more"]["hidden"] is False, middle["comments-more"]
    # the first step found exactly one button and its click reached it
    assert (page["steps"][0]["matches"], page["steps"][0]["dispatched"]) == (1, [True]), page["steps"]
    assert _thread_urls(page, page["steps"][0]["requestsSoFar"]) == [_list_url(0), _list_url(20)], _thread_urls(page)
    # the second click asks from the advanced offset, once
    assert _thread_urls(page) == [_list_url(0), _list_url(20), _list_url(40)], _thread_urls(page)
    # the last batch is a full 20, so only a count held against the total hides here, where a short-batch rule would keep the button
    assert _bodies(last) == [f"comment {i}" for i in range(1, 61)], (last["comments-list"], page["rejections"])
    assert last["comments-more"]["hidden"] is True, last["comments-more"]


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


def test_a_double_clicked_reply_toggle_fetches_the_tree_once_shows_pre_order_depth_rows_and_hides_and_reshows_them_without_a_request(bundle):
    page = _page(bundle, _music(), initially_hidden=["comments-more"], comments={"threads?start=0": THREADS, "/api/v1/videos/v1/comment-threads/7": TREE},
                 steps=[{"click": SHOW, "times": 2}, {"click": HIDE}, {"click": SHOW}])
    first, expanded, collapsed, reshown = page["snapshots"]
    steps = page["steps"]

    # control: before any click both threads rendered from the first batch and no thread-detail request had been made, so a detail request below came from a click
    assert [_texts(thread, "comment-body") for thread in _elements(first["comments-list"], "comment-thread")] == [["a thread nobody answered"], ["a thread with replies"]], (first["comments-list"], page["rejections"])
    assert DETAIL not in page["requestedUrls"][:page["startRequests"]], page["requestedUrls"]
    # a toggle with no in-flight guard sends the detail request twice for the two clicks
    assert page["requestedUrls"][:steps[0]["requestsSoFar"]].count(DETAIL) == 1, (page["requestedUrls"], steps, page["controls"][0], page["rejections"])
    # the toggle was the only shown control, labelled from totalReplies (4) and not from the 3 rows it will show; thread 8, with no replies, has none; the first click of the pair reached it
    assert page["controls"][0] == [SHOW], page["controls"][0]
    assert steps[0]["matches"] == 1 and steps[0]["dispatched"][0] is True, steps
    other, thread = _elements(expanded["comments-list"], "comment-thread")
    containers = _elements(thread, "comment-replies")
    assert [container["hidden"] for container in containers] == [False], (thread, page["rejections"])
    # pre-order: breadth-first gives r1, r4, r2; post-order gives r2 first; a flat or zero-based depth gives other classes; rendering every deleted reply adds r3 as a fourth row; dropping every deleted reply loses r1
    assert _rows(containers[0]) == ROWS, containers[0]
    assert _elements(containers[0], "comment-reply")[0]["text"] == "Comment deleted", containers[0]
    assert page["controls"][1].count(HIDE) == 1 and SHOW not in page["controls"][1], page["controls"][1]
    assert _elements(other, "comment-replies") == [] and _elements(other, "comment-reply") == [], other
    # hiding: the click reached "Hide replies", the container hid, and the label went back to the total, not to the 3 rows shown
    assert (steps[1]["matches"], steps[1]["dispatched"]) == (1, [True]), steps
    assert [container["hidden"] for container in _elements(_elements(collapsed["comments-list"], "comment-thread")[1], "comment-replies")] == [True], collapsed["comments-list"]
    assert page["controls"][2].count(SHOW) == 1 and HIDE not in page["controls"][2], page["controls"][2]
    # re-showing: the same three rows once each, where appending the tree again on each show holds six
    assert (steps[2]["matches"], steps[2]["dispatched"]) == (1, [True]), steps
    containers = _elements(_elements(reshown["comments-list"], "comment-thread")[1], "comment-replies")
    assert [container["hidden"] for container in containers] == [False], reshown["comments-list"]
    assert _rows(containers[0]) == ROWS, containers[0]
    # no request of any kind after the first step, and the detail URL once over the whole run
    assert steps[2]["requestsSoFar"] == steps[0]["requestsSoFar"], (page["requestedUrls"][steps[0]["requestsSoFar"]:], steps)
    assert page["requestedUrls"].count(DETAIL) == 1, page["requestedUrls"]
