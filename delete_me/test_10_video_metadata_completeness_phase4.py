"""The video page's taxonomy block, run in node with the real page module: it shows the category, language and tags from `/api/video` as text.

- For a body with a category, a language and two tags, the category and language items are shown with the body's values, and the tag list holds one `tag-chip` per tag, in order, whose text is the tag.
- For a body with an empty category, language and tag list, the category and language items are hidden and the tag list's only child reads "No tags".
- For a body with a category, an empty language and one tag, only the language item is hidden and the tag list holds one chip.

The runner stubs the browser platform node lacks: a `document` of recording elements, `window.location`, the storages, `ResizeObserver` and `getComputedStyle` for the collapsible description, and `fetch`, which answers `/api/video` with the case's body and `{}` elsewhere. Each taxonomy item starts in the opposite visibility to the one expected, so the page has to set it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
TITLE = "Taxonomy fixture title"
ITEMS = ["video-category", "video-language"]

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
    addEventListener() {}, insertAdjacentHTML() {}, remove() {},
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
const requested = [];
globalThis.fetch = async (input) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requested.push(url.pathname);
  const body = url.pathname === "/api/video" ? process.env.VIDEO_BODY : "{}";
  return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
};
await import(process.env.BUNDLE);
// Every stubbed fetch resolves at once, so loadVideo has settled within a few macrotasks.
for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
const report = (id) => ({ text: byId.get(id)?.textContent ?? null, hidden: byId.get(id)?.hidden ?? null });
const ids = ["video-title", "video-category", "video-category-value", "video-language", "video-language-value"];
const tags = (byId.get("video-tags")?.children ?? []).map((c) => ({ text: c.textContent, chip: c.nodeType === 1 && c.classList.contains("tag-chip") }));
process.stdout.write(JSON.stringify({ requested, ...Object.fromEntries(ids.map((id) => [id, report(id)])), tags }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_taxonomy")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path, body: dict, initially_hidden: list[str]) -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, **body}), "INITIALLY_HIDDEN": json.dumps(initially_hidden)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page asked /api/video and rendered its body, so the block below saw that body
    assert "/api/video" in page["requested"], page
    assert page["video-title"]["text"] == TITLE, page
    return page


def test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag(bundle):
    page = _page(bundle, {"category": "Science & Technology", "language": "English", "tags": ["alpha", "beta"]}, initially_hidden=ITEMS)

    assert page["video-category"]["hidden"] is False, page  # C1
    assert page["video-category-value"]["text"] == "Science & Technology", page  # C1
    assert page["video-language"]["hidden"] is False, page  # C1
    assert page["video-language-value"]["text"] == "English", page  # C1
    assert page["tags"] == [{"text": "alpha", "chip": True}, {"text": "beta", "chip": True}], page  # C1


def test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags(bundle):
    page = _page(bundle, {"category": "", "language": "", "tags": []}, initially_hidden=[])

    assert page["video-category"]["hidden"] is True, page  # C2
    assert page["video-language"]["hidden"] is True, page  # C2
    assert [child["text"] for child in page["tags"]] == ["No tags"], page  # C2


def test_an_empty_language_alone_hides_only_the_language_item(bundle):
    page = _page(bundle, {"category": "Music", "language": "", "tags": ["solo"]}, initially_hidden=["video-category"])

    assert page["video-category"]["hidden"] is False, page  # C1
    assert page["video-category-value"]["text"] == "Music", page  # C1
    assert page["video-language"]["hidden"] is True, page  # C2
    assert page["tags"] == [{"text": "solo", "chip": True}], page  # C1
