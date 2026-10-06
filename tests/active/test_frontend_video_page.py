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

Follow buttons, with the module run in node on a second harness, a recording DOM that parses innerHTML (`DOM_JS` + `PAGE_RUNNER`), the buttons seeded from video-page.html's own markup:
- Keyed, with `/api/video` carrying `channelId` and `accountUrl` and a list holding the video's channel, it reads "Unfollow channel" and "Follow account" at load. Follow account posts the video form and flips to "Unfollow account". Block channel resets the channel button to "Follow channel" and leaves the account button as it is. Follow channel posts the video form and flips back. Unfollow account posts the account key to remove and flips to "Follow account".
- Keyless, both buttons read "Follow …", a click on each shows "Following needs a profile. Create one from the Profile button on the home page.", and nothing is sent to the follow routes.
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


# --- the follow buttons, on a recording DOM that parses innerHTML ---

KEY_STORAGE = {"profileKey:v1": "K" * 43}
NEEDS_PROFILE_VIDEO_PAGE = "Following needs a profile. Create one from the Profile button on the home page."

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
    """The video page module bundled as `video.mjs`, beside the follow-control runner."""
    out = tmp_path_factory.mktemp("follow_pages")
    _esbuild(FRONTEND / "src" / "pages" / "video-page" / "index.ts", out / "video.mjs")
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


def _follow_page(pages: Path, page: str, *, storage: dict, answers: dict, steps: list[dict] = (), search: str = "", pathname: str = "/", held: list[str] = (), seeds: dict | None = None, row_names: list[str] = ()) -> dict:
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


PEER = "peer.example"
ALICE = "https://peer.example/accounts/alice"
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
    page = _follow_page(pages, "video", storage=KEY_STORAGE, search=VIDEO_SEARCH, pathname="/video-page.html", seeds=_seeds("video-page.html"), answers=answers,
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
    page = _follow_page(pages, "video", storage={}, search=VIDEO_SEARCH, pathname="/video-page.html", seeds=_seeds("video-page.html"), answers=_video_answers(),
                 steps=[{"click": "Follow channel"}, {"click": "Block channel"}, {"click": "Follow account"}])
    # A fresh page clicked on the account button alone, so the message it shows cannot be one the channel click left behind.
    alone = _follow_page(pages, "video", storage={}, search=VIDEO_SEARCH, pathname="/video-page.html", seeds=_seeds("video-page.html"), answers=_video_answers(), steps=[{"click": "Follow account"}])
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
