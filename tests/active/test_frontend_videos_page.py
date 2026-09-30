"""The home page's Profile modal holds a "Hide NSFW videos" checkbox, in each profile state, that reloads the home feed under its new value and leaves the page fetched under that value shown.

`pages/videos/index.ts` is bundled and run in node against recording elements and a stub fetch. It runs for a keyless visitor, a visitor holding a key, and one who has just clicked "Create profile" (the issued-key view).

- The first feed request is to /recommendations with mode recommendations and no nsfw, and its response is held.
- The Profile modal holds exactly one checkbox, and it is checked.
- Unchecking the box (click, input, change) sends exactly one more feed request, with mode recommendations and nsfw=1, which is answered at once. The held first page is then released and read by the page, and the feed shows the second page's rows.
- Checking it again sends one more feed request, with no nsfw, and the feed shows that third page's rows.

The feed is read as the `data-video-key`s in `#video-cards`. The checkbox's label text, its place in the modal and its styling are not asserted.
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
PROFILE_KEY = "profileKey:v1"

# The home page module runs against recording elements created on first lookup. The first feed request's response is held until the toggle's own response has been answered and settled, then released, so a load that renders whatever resolves last shows the first page.
HOME_RUNNER = """
const memory = (seed) => { const s = new Map(Object.entries(seed)); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory(JSON.parse(process.env.STORAGE));
globalThis.sessionStorage = memory({});
globalThis.window = { location: { origin: process.env.BASE, pathname: "/", search: "" }, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage,
  innerHeight: 800, scrollY: 0, addEventListener() {}, confirm: () => true };
const text = (v) => ({ nodeType: 3, textContent: String(v), parentElement: null });
const element = (tag) => {
  const el = { nodeType: 1, tagName: tag.toUpperCase(), hidden: false, disabled: false, checked: false, value: "", children: [], dataset: {}, style: {}, attrs: {}, listeners: {}, parentElement: null, html: null, className: "",
    get textContent() { return el.html ?? el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.html = null; el.children = v == null || v === "" ? [] : [text(v)]; },
    get innerHTML() { return el.html ?? ""; },
    set innerHTML(v) { el.children = []; el.html = String(v); },
    get type() { return el.attrs.type ?? ""; }, set type(v) { el.attrs.type = String(v); },
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    append: (...items) => { for (const item of items) { const node = typeof item === "string" ? text(item) : item; node.parentElement = el; el.children.push(node); } },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { el.html = null; el.children = []; el.append(...items); },
    setAttribute: (n, v) => { if (n === "hidden") el.hidden = true; else if (n === "checked") el.checked = true; else el.attrs[n] = String(v); },
    removeAttribute: (n) => { if (n === "hidden") el.hidden = false; else if (n === "checked") el.checked = false; else delete el.attrs[n]; },
    hasAttribute: (n) => (n === "hidden" ? el.hidden : n in el.attrs), getAttribute: (n) => el.attrs[n] ?? null,
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); }, removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    insertAdjacentHTML: (p, h) => { el.html = (el.html ?? "") + String(h); },
    closest: () => null, querySelector: () => null, querySelectorAll: () => [], focus() {}, select() {}, remove() {},
  };
  return el;
};
const byId = new Map();
// A tall document keeps the page from filling the viewport with more batches, so the only feed requests are the loads.
globalThis.document = { title: "", body: element("body"), documentElement: { scrollHeight: 100000 },
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div")); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (v) => text(v), querySelector: () => null, querySelectorAll: () => [], addEventListener() {} };
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
const pages = JSON.parse(process.env.PAGES);
const feed = [];
let release = null;
let firstBodyRead = false;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/profile") return new Response(JSON.stringify({ key: process.env.ISSUED_KEY, profile_id: "p1" }), { status: 201, headers });
  if (url.pathname !== "/recommendations") return new Response("{}", { status: 404, headers });
  const i = feed.length;
  feed.push({ mode: url.searchParams.getAll("mode"), nsfw: url.searchParams.getAll("nsfw") });
  const response = new Response(JSON.stringify({ rows: pages[i] ?? [] }), { status: 200, headers });
  if (i !== 0) return response;
  await new Promise((resolve) => { release = resolve; });
  const json = response.json.bind(response);
  response.json = async () => { firstBodyRead = true; return json(); };
  return response;
};
const rejections = [];
process.on("unhandledRejection", (r) => { rejections.push(String(r && r.stack || r)); });
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 10)); };
// Events bubble through parentElement, so a listener on the input, its label or the section all hear it.
const fire = (target, type) => { const event = { type, target, bubbles: true, preventDefault() {}, stopPropagation() {} };
  for (let node = target; node; node = node.parentElement) { event.currentTarget = node; for (const l of [...(node.listeners[type] ?? [])]) l.call(node, event); } };
// A user's click on a checkbox flips it, then dispatches click, input and change.
const toggle = (box) => { box.checked = !box.checked; for (const type of ["click", "input", "change"]) fire(box, type); };
const descend = (n) => (n?.nodeType === 1 ? [n, ...n.children.flatMap(descend)] : []);
const section = () => byId.get("profile-section");
const cardKeys = () => [...(byId.get("video-cards")?.innerHTML ?? "").matchAll(/data-video-key="([^"]+)"/g)].map((m) => m[1]);
await import(process.env.BUNDLE);
await settle();
const report = { feedAtStart: feed.map((f) => ({ ...f })), heldAtStart: release !== null };
fire(byId.get("show-profile-header"), "click");
await settle();
if (process.env.PROFILE_STATE === "issued-key") {
  fire(descend(section()).find((n) => n.tagName === "BUTTON" && n.textContent === "Create profile"), "click");
  await settle();
}
report.intro = section().children[0]?.textContent ?? null;
const boxes = descend(section()).filter((n) => n.tagName === "INPUT" && n.type === "checkbox");
report.checkboxes = boxes.map((b) => ({ checked: b.checked }));
if (boxes.length) {
  toggle(boxes[0]);
  await settle();
}
report.afterOff = { feed: feed.map((f) => ({ ...f })), cards: cardKeys() };
release?.();
await settle();
report.afterRelease = { cards: cardKeys(), firstBodyRead };
if (boxes.length) {
  toggle(boxes[0]);
  await settle();
}
report.afterOn = { feed: feed.map((f) => ({ ...f })), cards: cardKeys() };
report.rejections = rejections;
process.stdout.write(JSON.stringify(report) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def home_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("home")
    run = subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "videos" / "index.ts"), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    (out / "runner.mjs").write_text(HOME_RUNNER)
    return out


def _rows(tag: str) -> list[dict]:
    # views and likes on the row keep the page from fetching live stats from the instance.
    return [{"video_id": f"{tag}{i}", "video_uuid": f"uuid-{tag}{i}", "instance_domain": "peer.example", "title": f"{tag} {i}", "views": 1, "likes": 1} for i in range(1, 4)]


def _keys(rows: list[dict]) -> list[str]:
    return [f"{row['instance_domain']}::{row['video_uuid']}" for row in rows]


# The first load's page, the page fetched after turning the filter off, and the one after turning it back on.
FIRST, TURNED_OFF, TURNED_ON = _rows("a"), _rows("b"), _rows("c")
PROFILE_STATES = {
    "keyless": ({}, "No profile."),
    "key-holding": ({PROFILE_KEY: "K" * 43}, "This browser holds a profile key."),
    "issued-key": ({}, "This is the only copy of your key."),
}
HOME_FEED = ["recommendations"]


@pytest.mark.parametrize("state", PROFILE_STATES)
def test_the_checked_profile_checkbox_reloads_the_home_feed_under_each_new_setting_and_shows_that_page(home_bundle, state):
    storage, intro = PROFILE_STATES[state]
    proc = subprocess.run(
        ["node", str(home_bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(home_bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps(storage),
             "PAGES": json.dumps([FIRST, TURNED_OFF, TURNED_ON]), "ISSUED_KEY": "I" * 43, "PROFILE_STATE": state},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])

    # control: the page made its first feed request filtered and its response is held, and the modal rendered the state under test, so the checkbox is looked for in that branch
    assert page["feedAtStart"] == [{"mode": HOME_FEED, "nsfw": []}] and page["heldAtStart"] is True, page
    assert (page["intro"] or "").startswith(intro), (page["intro"], page["rejections"])
    # A checkbox left out of this branch, or built unchecked, fails here.
    assert page["checkboxes"] == [{"checked": True}], (page["checkboxes"], page["rejections"])
    # Unchecking reloads the same feed once, now opted in; a handler that saves without reloading adds no request, and a URL built from a setting captured at page load carries no nsfw.
    assert page["afterOff"]["feed"] == [{"mode": HOME_FEED, "nsfw": []}, {"mode": HOME_FEED, "nsfw": ["1"]}], (page["afterOff"], page["rejections"])
    # control: the held first page reached the page after the toggle's page had rendered, so the stale result was there to be dropped
    assert page["afterRelease"]["firstBodyRead"] is True, page["afterRelease"]
    # A load that renders whichever response arrives last shows the first page's keys here.
    assert page["afterRelease"]["cards"] == _keys(TURNED_OFF), (page["afterOff"]["cards"], page["afterRelease"], page["rejections"])
    # Checking it again reloads filtered; a handler that always turns the filter off sends nsfw=1 again.
    assert page["afterOn"]["feed"][2:] == [{"mode": HOME_FEED, "nsfw": []}], page["afterOn"]
    assert page["afterOn"]["cards"] == _keys(TURNED_ON), (page["afterOn"], page["rejections"])
