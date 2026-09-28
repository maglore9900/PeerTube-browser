"""The video page, run in node with the real page module: its taxonomy block shows `/api/video`'s category, language and tags as text, and its comments section shows the first page of the source instance's comment threads as text.

- For a body with a category, a language and two tags, the category and language items are shown with the body's values, and the tag list holds one `tag-chip` per tag, in order, whose text is the tag.
- For a body with an empty category, language and tag list, the category and language items are hidden and the tag list's only child reads "No tags".
- For a body with a category, an empty language and one tag, only the language item is hidden and the tag list holds one chip.
- By the time the page module's import has resolved, before any timer tick, the page has requested `comment-threads?start=0&count=20&sort=-createdAt` from the video's host. For a first page with a total of 3 holding two live threads around a deleted thread with no replies, the heading reads "Comments (3)" and the list holds one `comment-thread` for each live thread, in order. Each thread holds exactly one author (the display name), one `@name@host` handle built from the account's own host (one account is on a host other than the video's), one relative time and one body with its line break kept. The "more" control is hidden and the status is empty.
- For a first page of two threads under a total of 57, the heading reads "Comments (57)". A display name shaped like an `<img onerror>` tag reads literally. A federated HTML body with an encoded `<script>`, a raw `<script>` and a `<b onclick>` reads as its plain text. A body that is not HTML-shaped (markdown, a spaced `< b >` and an `&amp;` entity, which HTML reduction would strip and decode) reads raw. No node under the heading, list, status or "more" control is markup set through innerHTML, and none received insertAdjacentHTML.

The runner stubs the browser platform that node lacks: a `document` of recording elements, `window.location`, the storages, `ResizeObserver` and `getComputedStyle` for the collapsible description, and `fetch`. `fetch` answers `/api/video` with the case's body. It answers the thread list (keyed `threads?start=N`) and other paths (keyed by pathname) from the case's `COMMENTS` map, and answers `{}` for unmapped paths. Each taxonomy item, and the comments "more" control, starts in the opposite visibility to the one expected, so the page has to set it. innerHTML leaves an opaque type-0 node and insertAdjacentHTML is counted per element, so markup cannot pass for text; the runner also reports which page elements each detector caught, so a clean comments walk is shown to come from detectors that fire.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
TITLE = "Taxonomy fixture title"
ITEMS = ["video-category", "video-language"]
COMMENT_ROOTS = ["comments-heading", "comments-list", "comments-status", "comments-more"]
FIRST_PAGE_URL = "https://peer.example/api/v1/videos/v1/comment-threads?start=0&count=20&sort=-createdAt"

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: "?id=v1&host=peer.example" },
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
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div", initiallyHidden.includes(id))); return byId.get(id); },
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
await import(process.env.BUNDLE);
// Only what the page asked for by the time its import resolved, before any timer tick: a request chained behind another load's response is not here yet.
const startUrls = [...requestedUrls];
// Every stubbed fetch resolves at once, so the page's loads have settled within a few macrotasks.
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
const walk = (node) => (node == null ? null : node.nodeType !== 1 ? { type: node.nodeType, text: node.textContent } : {
  type: 1, tag: node.tagName, cls: node.className, text: node.textContent, hidden: node.hidden, attrs: { ...node.attrs },
  markup: markupCalls.filter((call) => call.el === node).length, children: node.children.map(walk) });
const snapshots = [];
const snapshot = () => snapshots.push(Object.fromEntries(JSON.parse(process.env.COMMENT_ROOTS).map((id) => [id, walk(byId.get(id))])));
await settle();
snapshot();
const report = (id) => ({ text: byId.get(id)?.textContent ?? null, hidden: byId.get(id)?.hidden ?? null });
const ids = ["video-title", "video-category", "video-category-value", "video-language", "video-language-value"];
const tags = (byId.get("video-tags")?.children ?? []).map((c) => ({ text: c.textContent, chip: c.nodeType === 1 && c.classList.contains("tag-chip") }));
// Which page elements the detectors caught markup on, so a clean comments walk is shown to come from detectors that do fire.
const idOf = (node) => [...byId.entries()].find(([, el]) => el === node)?.[0] ?? null;
const markupIds = markupCalls.map((call) => idOf(call.el));
const opaqueIds = [...byId.entries()].filter(([, el]) => el.children.some((c) => c.nodeType === 0)).map(([id]) => id);
process.stdout.write(JSON.stringify({ requested, requestedUrls, startUrls, snapshots, markupIds, opaqueIds, ...Object.fromEntries(ids.map((id) => [id, report(id)])), tags }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_comments")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path, body: dict, initially_hidden: list[str], comments: dict | None = None) -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, **body}), "INITIALLY_HIDDEN": json.dumps(initially_hidden),
             "COMMENTS": json.dumps(comments or {}), "COMMENT_ROOTS": json.dumps(COMMENT_ROOTS)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page asked /api/video and rendered its body, so the block below saw that body
    assert "/api/video" in page["requested"], page
    assert page["video-title"]["text"] == TITLE, page
    return page


def _created(ago: timedelta) -> str:
    return (datetime.now(timezone.utc) - ago).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _thread(thread_id: int, name: str, display_name: str, text: str, ago: timedelta, host: str = "peer.example") -> dict:
    return {"id": thread_id, "threadId": thread_id, "text": text, "createdAt": _created(ago), "isDeleted": False, "totalReplies": 0,
            "account": {"name": name, "host": host, "displayName": display_name}}


def _elements(node: dict | None, cls: str) -> list[dict]:
    found = []
    for child in (node or {}).get("children", []):
        if child["type"] == 1 and cls in child["cls"].split():
            found.append(child)
        found.extend(_elements(child, cls))
    return found


def _field(threads: list[dict], cls: str) -> list[list[str]]:
    return [[node["text"] for node in _elements(thread, cls)] for thread in threads]


def _all_nodes(node: dict | None) -> list[dict]:
    if node is None:
        return []
    return [node, *(n for child in node.get("children", []) for n in _all_nodes(child))]


def test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag(bundle):
    page = _page(bundle, {"category": "Science & Technology", "language": "English", "tags": ["alpha", "beta"]}, initially_hidden=ITEMS)

    assert page["video-category"]["hidden"] is False, page
    assert page["video-category-value"]["text"] == "Science & Technology", page
    assert page["video-language"]["hidden"] is False, page
    assert page["video-language-value"]["text"] == "English", page
    assert page["tags"] == [{"text": "alpha", "chip": True}, {"text": "beta", "chip": True}], page


def test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags(bundle):
    page = _page(bundle, {"category": "", "language": "", "tags": []}, initially_hidden=[])

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
    page = _page(bundle, {}, initially_hidden=[], comments={"threads?start=0": {"body": first_page}})
    snap = page["snapshots"][-1]
    threads = _elements(snap["comments-list"], "comment-thread")

    # control: the page's own first fetch is in the start record, so an empty record would mean the capture was broken rather than the comments late
    assert f"{BASE}/api/video?id=v1&host=peer.example" in page["startUrls"], page["startUrls"]
    assert FIRST_PAGE_URL in page["startUrls"], page["startUrls"]  # C1
    assert FIRST_PAGE_URL in page["requestedUrls"], page["requestedUrls"]  # C1
    assert snap["comments-heading"]["text"] == "Comments (3)", snap["comments-heading"]  # C1
    assert len(threads) == 2, snap["comments-list"]  # C1
    assert _field(threads, "comment-author") == [["Alice"], ["Bob"]], threads  # C1
    # bob's account is on a host other than the video's, so only a handle built from account.host reads right
    assert _field(threads, "comment-handle") == [["@alice@peer.example"], ["@bob@tube.other.example"]], threads  # C1
    assert _field(threads, "comment-body") == [["line one\nline two"], ["hi from bob"]], threads  # C1
    assert _field(threads, "comment-time") == [["3 hours ago"], ["2 days ago"]], threads  # C1
    assert snap["comments-more"]["hidden"] is True, snap["comments-more"]  # C1
    assert snap["comments-status"]["text"] == "", snap["comments-status"]  # C1


def test_hostile_names_and_federated_html_reach_the_comments_only_as_text(bundle):
    hostile_name = "<img src=x onerror=alert(1)>"
    federated = '&lt;script&gt;alert(1)&lt;/script&gt;<script>alert(2)</script><b onclick="alert(3)">bold</b>'
    first_page = {"total": 57, "data": [
        _thread(1, "mallory", hostile_name, federated, timedelta(hours=1)),
        # not HTML-shaped (no `<` before a letter or `/`), yet HTML reduction would strip `< b >` and decode `&amp;`, so raw and reduced read differently
        _thread(2, "carol", "Carol", "**bold** a < b > c &amp; d", timedelta(hours=2)),
    ]}
    page = _page(bundle, {}, initially_hidden=[], comments={"threads?start=0": {"body": first_page}})
    snap = page["snapshots"][-1]
    threads = _elements(snap["comments-list"], "comment-thread")
    every_node = [node for root in COMMENT_ROOTS for node in _all_nodes(snap[root])]

    # control: both detectors fire on the page's own markup outside the comments, so an empty count below is not a dead detector
    assert "like-button" in page["markupIds"], page["markupIds"]
    assert "similar-videos" in page["opaqueIds"], page["opaqueIds"]
    # both threads rendered with their authors as text, which also arms the two absence checks below with real comment nodes
    assert _field(threads, "comment-author") == [[hostile_name], ["Carol"]], threads  # C2
    # 57 in total, two rows on this page: only a heading read from `total` gives 57, where the page's row count and the shown threads both give 2 (Case A's 3 cannot tell `total` from its 3 rows)
    assert snap["comments-heading"]["text"] == "Comments (57)", snap["comments-heading"]  # C1
    assert _field(threads, "comment-body") == [["<script>alert(1)</script>alert(2)bold"], ["**bold** a < b > c &amp; d"]], threads  # C2
    assert [node for node in every_node if node["type"] == 0] == [], every_node  # C2
    assert sum(node.get("markup", 0) for node in every_node) == 0, every_node  # C2
