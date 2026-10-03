"""The video page, run in node with the real page module and the embed API stood in: the Translate toggle shows, labelled "Translate", only once the player built on `#video-embed` has resolved `ready` and a profile key is held, and before that no `/api/translate` request is made; with Translate stored on at load, the overlay shows as one text node the cue containing each position the player reports, a seek back included.

Toggle (C1):
- With a key and Translate stored on, the toggle is still hidden and `/api/translate` unasked when the page has loaded and `ready` has not yet resolved. Once it resolves, the toggle is shown and reads "Translate" (surrounding whitespace aside), and one player was built, on `#video-embed`.
- No key (with Translate stored on and `ready` resolving), a `ready` that never settles, a `ready` that rejects, and a constructor that throws a string each leave the toggle hidden in every snapshot, ask `/api/translate` nothing, leave no unhandled rejection, and still point `#original-link` at the body's `originalUrl`. The same page with a key and a resolving `ready` shows the toggle and asks once.

Overlay (C2), with a key and Translate stored on at load:
- One player is built, on `#video-embed`, whose src already read `https://peer.example/videos/embed/uuid-1?api=1` when it was built. Exactly one `/api/translate` request is made, with the query `id=uuid-1&host=peer.example` (the body's `videoUuid`, not the page's `?id=v1`) and the stored key, and none had been made when the runner resolved `ready`.
- Reported positions 1.5, 3, 7, 0.5, 1.0, 9.5 and 12 show, in turn, "First cue", nothing (hidden), "Seven cue", "Zero cue" (a seek back to an earlier cue), "First cue" (1.0 is where "Zero cue" ends and "First cue" starts), the literal "<b>x</b>", and nothing (hidden) after the last cue. The "<b>x</b>" overlay is one text node, the overlay received no insertAdjacentHTML, and no snapshot of it holds markup set through innerHTML, while both detectors do catch the page's own markup elsewhere.

Supporting:
- A `none` state, asked once, reads exactly "No English translation is available for this video." and a reported position shows nothing.
- With Translate not stored, the shown toggle asks nothing and a reported position shows nothing. A click stores `on` and asks once, after which 1.5 shows "First cue"; a second click stores `off`, hides the overlay, asks nothing more, and a later 7 shows nothing.
- For a keyless visitor the embed src gains `api=1` beside an existing `start=10` query or as the only one, and a `javascript:` URL or an unparseable `https://[bad` sets no src.
- With no position reported at all and the player at 7, within 8 s the page has asked `getCurrentPosition` and shows "Seven cue".

The runner stubs the browser platform as `tests/active/test_frontend_video_page.py` does (recording elements, storages, `fetch`), seeds the toggle with video-page.html's own label, and starts the toggle and overlay hidden, so the page has to set their visibility. `@peertube/embed-api` is aliased at bundle time to a stand-in, because a real player talks to an instance's embed over postMessage and node has no iframe; the stand-in records each construction, the iframe and its src at that moment, and each `getCurrentPosition` call, and its `ready` is created in the constructor as the library's is, then resolved or rejected by the runner after the page has loaded (or left pending, or the constructor throws a string, as jschannel does). Each step clicks an element by id, reports a position to every `playbackStatusUpdate` listener, moves the player without reporting, or waits; the run snapshots the toggle, status and overlay, the stored setting and the request count before `ready` settles, after, and after each step.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
HOST = "peer.example"
TITLE = "Translate fixture title"
EMBED = "https://peer.example/videos/embed/uuid-1"
ORIGINAL = "https://peer.example/videos/watch/uuid-1"
KEY = "translate-profile-key"
TOGGLE = "translate-toggle"
STATUS = "translate-status"
OVERLAY = "translate-overlay"
NO_TRANSLATION = "No English translation is available for this video."
CUES = [
    {"start": 0.25, "end": 1.0, "text": "Zero cue"},
    {"start": 1.0, "end": 2.0, "text": "First cue"},
    {"start": 6.0, "end": 8.0, "text": "Seven cue"},
    {"start": 9.0, "end": 10.0, "text": "<b>x</b>"},
]
READY = {"status": 200, "body": {"state": "ready", "cues": CUES}}
NONE = {"status": 200, "body": {"state": "none"}}
# The toggle's label as video-page.html writes it, so a page that shows the toggle is held to the real markup's label.
INITIAL_TEXT = {match.group(1): html.unescape(match.group(2)) for match in re.finditer(r'id="(translate-toggle)"[^>]*>([^<]*)<', (FRONTEND / "video-page.html").read_text())}

EMBED_STUB = """
// Stands in for @peertube/embed-api: a real player talks to the instance's embed over postMessage, and node has no iframe.
const api = () => globalThis.__embedApi;
export class PeerTubePlayer {
  constructor(iframe) {
    const state = api();
    state.constructed += 1;
    state.iframes.push(iframe);
    state.srcAtConstruction.push(iframe?.src ?? null);
    // jschannel throws strings, not Errors, when it cannot bind a channel to the iframe.
    if (state.mode === "throw") throw "Channel.build() called without a valid window argument";
    this.listeners = {};
    state.players.push(this);
    // Created here as the library's is; the runner settles it once the page has loaded, and `never` leaves it pending. The library rejects with no reason.
    this.readyPromise = new Promise((resolve, reject) => {
      if (state.mode === "resolve") state.releases.push(() => resolve());
      if (state.mode === "reject") state.releases.push(() => reject());
    });
  }
  get ready() { return this.readyPromise; }
  addEventListener(name, handler) { (this.listeners[name] ??= []).push(handler); return true; }
  removeEventListener(name, handler) { this.listeners[name] = (this.listeners[name] ?? []).filter((h) => h !== handler); return true; }
  getCurrentPosition() { const state = api(); state.positionCalls += 1; return Promise.resolve(state.position); }
}
"""

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
for (const [k, v] of Object.entries(JSON.parse(process.env.STORAGE))) localStorage.setItem(k, v);
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
    get innerText() { return el.textContent; },
    set innerText(v) { el.textContent = v; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? "").join(""); },
    set innerHTML(v) { el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    get href() { return el.attrs.href ?? ""; },
    set href(v) { el.attrs.href = String(v); },
    // src is an attribute as in the browser, so removeAttribute("src") clears what `el.src =` set.
    get src() { return el.attrs.src ?? ""; },
    set src(v) { el.attrs.src = String(v); },
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
const initialText = JSON.parse(process.env.INITIAL_TEXT);
const seeded = (id) => { const el = element(id === "video-embed" ? "iframe" : "div", initiallyHidden.includes(id)); if (id in initialText) el.textContent = initialText[id]; return el; };
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, seeded(id)); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
// The embed API stand-in reads its mode here and records into it.
const embed = globalThis.__embedApi = { mode: process.env.READY, constructed: 0, iframes: [], srcAtConstruction: [], players: [], releases: [], positionCalls: 0, position: null };
const translateAnswer = JSON.parse(process.env.TRANSLATE);
const requests = [];
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ url: url.href, key: new Headers(init?.headers ?? input?.headers ?? {}).get("x-profile-key") });
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/video") return new Response(process.env.VIDEO_BODY, { status: 200, headers });
  if (url.pathname === "/api/translate") return new Response(JSON.stringify(translateAnswer.body), { status: translateAnswer.status, headers });
  return new Response("{}", { status: 200, headers });
};
const warned = [];
console.warn = (...args) => { warned.push(String(args[0])); };
// A failure that escapes the page would otherwise end node before the report; recorded, it is shown next to the state the page left.
const rejections = [];
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
await import(process.env.BUNDLE);
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
const walk = (node) => (node == null ? null : node.nodeType !== 1 ? { type: node.nodeType, text: node.textContent } : {
  type: 1, tag: node.tagName, text: node.textContent, hidden: node.hidden, attrs: { ...node.attrs },
  markup: markupCalls.filter((call) => call.el === node).length, children: node.children.map(walk) });
const ids = JSON.parse(process.env.TRANSLATE_IDS);
const snapshots = [];
const snapshot = () => { snapshots.push({ ...Object.fromEntries(ids.map((id) => [id, walk(document.getElementById(id))])), stored: localStorage.getItem("translate:v1"), requests: requests.length }); };
// A user cannot click a disabled or unrendered button, so such a click never reaches the listeners; a listener's own throw is kept like a rejection.
const click = (el) => {
  if (el.disabled || el.hidden) return false;
  const event = { type: "click", target: el, currentTarget: el, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() {} };
  for (const listener of [...(el.listeners.click ?? [])]) { try { listener.call(el, event); } catch (error) { rejections.push(String(error)); } }
  return true;
};
await settle();
snapshot();
// ready settles only here, after the page has loaded, so a request counted below this mark was sent before ready resolved.
const readyAt = requests.length;
embed.releases.forEach((release) => release());
await settle();
snapshot();
const steps = [];
for (const step of JSON.parse(process.env.STEPS)) {
  if ("click" in step) steps.push(click(document.getElementById(step.click)));
  if ("emit" in step) {
    embed.position = step.emit;
    for (const player of embed.players) for (const handler of player.listeners.playbackStatusUpdate ?? []) handler({ position: step.emit, duration: 20, volume: 1, playbackState: "playing" });
    steps.push(true);
  }
  // The player moves without reporting it, so only a page that asks for the position learns it.
  if ("position" in step) { embed.position = step.position; steps.push(true); }
  if ("wait" in step) { await new Promise((resolve) => setTimeout(resolve, step.wait)); steps.push(true); }
  await settle();
  snapshot();
}
const idOf = (node) => [...byId.entries()].find(([, el]) => el === node)?.[0] ?? null;
const markupIds = markupCalls.map((call) => idOf(call.el));
const opaqueIds = [...byId.entries()].filter(([, el]) => el.children.some((c) => c.nodeType === 0)).map(([id]) => id);
process.stdout.write(JSON.stringify({ requests, readyAt, snapshots, steps, warned, rejections, markupIds, opaqueIds,
  title: byId.get("video-title")?.textContent ?? null, originalHref: byId.get("original-link")?.attrs.href ?? null, embedSrc: byId.get("video-embed")?.attrs.src ?? null,
  embed: { constructed: embed.constructed, iframes: embed.iframes.map(idOf), srcAtConstruction: embed.srcAtConstruction, positionCalls: embed.positionCalls } }) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("translate_page")
    (out / "embed-api.mjs").write_text(EMBED_STUB)
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}", f"--alias:@peertube/embed-api={out / 'embed-api.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path, *, key: str | None = KEY, stored: str | None = "on", ready: str = "resolve", embed: str = EMBED, translate: dict = READY, steps: list[dict] = ()) -> dict:
    storage = {name: value for name, value in (("profileKey:v1", key), ("translate:v1", stored)) if value is not None}
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "HOST": HOST, "STORAGE": json.dumps(storage), "READY": ready,
             "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, "embedUrl": embed, "originalUrl": ORIGINAL}), "TRANSLATE": json.dumps(translate),
             "INITIALLY_HIDDEN": json.dumps([TOGGLE, OVERLAY]), "INITIAL_TEXT": json.dumps(INITIAL_TEXT), "TRANSLATE_IDS": json.dumps([TOGGLE, STATUS, OVERLAY]), "STEPS": json.dumps(list(steps))},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page asked /api/video and rendered its body, and the run left a snapshot before ready settled, one after, and one per step
    assert "/api/video" in [urlsplit(request["url"]).path for request in page["requests"]], page["requests"]
    assert page["title"] == TITLE, page
    assert len(page["snapshots"]) == len(steps) + 2, page["snapshots"]
    return page


def _translate_requests(page: dict, upto: int | None = None) -> list[dict]:
    return [request for request in page["requests"][:upto] if urlsplit(request["url"]).path == "/api/translate"]


def _parts(url: str) -> tuple:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc, parts.path, parse_qs(parts.query)


def _overlay(snap: dict) -> tuple:
    return snap[OVERLAY]["text"], snap[OVERLAY]["hidden"]


def test_with_a_key_the_toggle_stays_hidden_and_translate_unasked_until_ready_resolves_then_shows_labelled_translate(bundle):
    page = _page(bundle)
    before, after = page["snapshots"]

    # hidden before ready resolves and shown after it, on the same page, so the hidden toggle is the wait for ready and not a toggle never shown
    assert (before[TOGGLE]["hidden"], after[TOGGLE]["hidden"]) == (True, False), (before[TOGGLE], after[TOGGLE], page["embed"], page["rejections"])
    assert _translate_requests(page, page["readyAt"]) == [], page["requests"]
    # "Translate" exactly, never "CC" or "Captions"
    assert after[TOGGLE]["text"].strip() == "Translate", (after[TOGGLE], INITIAL_TEXT)
    # one player, built on #video-embed, so the ready the toggle waited for is that player's
    assert page["embed"]["iframes"] == ["video-embed"], (page["embed"], page["rejections"])


BLOCKED = {
    "no key": {"key": None},
    "ready never settles": {"ready": "never"},
    "ready rejects": {"ready": "reject"},
    "constructor throws a string": {"ready": "throw"},
}


@pytest.mark.parametrize("case", BLOCKED.values(), ids=BLOCKED.keys())
def test_without_a_key_or_a_resolved_ready_there_is_no_toggle_no_translate_request_and_no_escaped_failure(bundle, case):
    page = _page(bundle, **case)
    granted = _page(bundle)

    blocked = ([snap[TOGGLE]["hidden"] for snap in page["snapshots"]], len(_translate_requests(page)))
    shown = ([snap[TOGGLE]["hidden"] for snap in granted["snapshots"]], len(_translate_requests(granted)))
    # the same page with a key and a resolving ready shows the toggle and asks once, so the hidden toggle and the silence of the blocked case are the gate's doing
    assert (shown, blocked) == (([True, False], 1), ([True, True], 0)), (granted["snapshots"], granted["requests"], granted["rejections"], page["snapshots"], page["requests"])
    # a rejected ready, or a thrown string, that escaped the page would be recorded here
    assert page["rejections"] == [], page["rejections"]
    # the original link is set after the embed block, so a throw out of the player setup would leave it unset
    assert page["originalHref"] == ORIGINAL, (page["originalHref"], page["rejections"])


# Positions reported in turn, and what the overlay then reads and whether it is hidden. 3 falls between cues and 12 after the last; 0.5 seeks back past the cue shown before it; 1.0 is where "Zero cue" ends and "First cue" starts.
SEEK = [1.5, 3, 7, 0.5, 1.0, 9.5, 12]
SHOWN = [("First cue", False), ("", True), ("Seven cue", False), ("Zero cue", False), ("First cue", False), ("<b>x</b>", False), ("", True)]


def test_loaded_with_translate_on_the_overlay_shows_as_text_the_cue_at_each_reported_position_including_after_a_seek_back(bundle):
    page = _page(bundle, steps=[{"emit": position} for position in SEEK])
    requests = _translate_requests(page)
    shown = [_overlay(snap) for snap in page["snapshots"][2:]]
    marked = page["snapshots"][2 + SEEK.index(9.5)][OVERLAY]

    # control: both detectors catch the page's own markup elsewhere, so the overlay's absence from them below is not a dead detector
    assert "like-button" in page["markupIds"], page["markupIds"]
    assert "similar-videos" in page["opaqueIds"], page["opaqueIds"]
    assert shown == SHOWN, (shown, page["embed"], page["requests"], page["rejections"])
    # the markup-shaped cue is one text node, so it reads literally and was not parsed
    assert [(child["type"], child["text"]) for child in marked["children"]] == [(3, "<b>x</b>")], marked
    assert OVERLAY not in page["markupIds"], page["markupIds"]
    # innerHTML leaves an opaque type-0 node, so none in any snapshot means the overlay never held markup between reports either
    assert [child for snap in page["snapshots"] for child in snap[OVERLAY]["children"] if child["type"] == 0] == [], [snap[OVERLAY] for snap in page["snapshots"]]
    # one player, on #video-embed, whose src already carried api=1 when it was built
    assert page["embed"]["iframes"] == ["video-embed"], (page["embed"], page["rejections"])
    assert _parts(page["embedSrc"]) == ("https", HOST, "/videos/embed/uuid-1", {"api": ["1"]}), page["embedSrc"]
    assert page["embed"]["srcAtConstruction"] == [page["embedSrc"]], page["embed"]
    assert len(requests) == 1, page["requests"]
    # the body's videoUuid, not the page's ?id=v1, and the stored key
    assert _parts(requests[0]["url"]) == ("http", "client.test", "/api/translate", {"id": ["uuid-1"], "host": [HOST]}), requests
    assert requests[0]["key"] == KEY, requests
    # asked once ready resolved: a request run alongside ready would already be counted when the runner resolved it
    assert _translate_requests(page, page["readyAt"]) == [], (page["readyAt"], page["requests"])


def test_a_none_state_reads_no_english_translation_and_a_reported_position_shows_nothing(bundle):
    page = _page(bundle, translate=NONE, steps=[{"emit": 1.5}])
    snap = page["snapshots"][-1]

    assert len(_translate_requests(page)) == 1, page["requests"]
    assert snap[STATUS]["text"] == NO_TRANSLATION, (snap[STATUS], page["rejections"])
    # control: with cues the same reported position shows "First cue", so the empty overlay below is the none state's doing
    ready = _page(bundle, steps=[{"emit": 1.5}])["snapshots"][-1]
    assert _overlay(ready) == ("First cue", False), ready[OVERLAY]
    assert _overlay(snap) == ("", True), snap[OVERLAY]


def test_a_click_stores_on_and_asks_once_and_a_second_click_stores_off_after_which_a_reported_position_shows_nothing(bundle):
    page = _page(bundle, stored=None, steps=[{"emit": 1.5}, {"click": TOGGLE}, {"emit": 1.5}, {"click": TOGGLE}, {"emit": 7}])
    ready, idle, on, playing, off, late = page["snapshots"][1:]

    # not stored at load: the toggle is shown, nothing is asked, and a reported position shows nothing
    assert ready[TOGGLE]["hidden"] is False, (ready[TOGGLE], page["rejections"])
    assert ready["stored"] is None, ready
    assert _translate_requests(page, idle["requests"]) == [], page["requests"]
    assert _overlay(idle) == ("", True), idle[OVERLAY]
    # both clicks reached a shown, enabled toggle
    assert page["steps"] == [True, True, True, True, True], page["steps"]
    assert on["stored"] == "on", on
    assert len(_translate_requests(page, on["requests"])) == 1, page["requests"]
    assert _overlay(playing) == ("First cue", False), (playing[OVERLAY], page["rejections"])
    assert off["stored"] == "off", off
    assert _overlay(off) == ("", True), off[OVERLAY]
    # 7 is inside "Seven cue", so only a page that ignores positions once off shows nothing here
    assert _overlay(late) == ("", True), late[OVERLAY]
    assert len(_translate_requests(page)) == 1, page["requests"]


# Each embedUrl and the src it leaves on #video-embed, as (scheme, host, path, query), or None for no src.
EMBEDS = {
    EMBED: ("https", HOST, "/videos/embed/uuid-1", {"api": ["1"]}),
    f"{EMBED}?start=10": ("https", HOST, "/videos/embed/uuid-1", {"start": ["10"], "api": ["1"]}),
    "javascript:alert(1)": None,
    "https://[bad": None,
}


def _src_parts(src: str | None) -> tuple | str | None:
    if not src:
        return None
    # An unparseable src is kept raw, so a page that set one reads as that string in the diff rather than erroring here.
    try:
        return _parts(src)
    except ValueError:
        return src


def test_the_embed_src_gains_api_1_with_or_without_a_query_and_a_javascript_or_unparseable_url_sets_no_src(bundle):
    srcs = {embed: _page(bundle, key=None, stored=None, embed=embed)["embedSrc"] for embed in EMBEDS}

    assert {embed: _src_parts(src) for embed, src in srcs.items()} == EMBEDS, srcs


def test_with_no_reported_position_the_overlay_follows_the_position_the_page_asks_the_player_for(bundle):
    page = _page(bundle, steps=[{"position": 7}, {"wait": 8000}])
    ready, last = page["snapshots"][1], page["snapshots"][-1]

    # control: nothing shows before the player has a position
    assert _overlay(ready) == ("", True), (ready[OVERLAY], page["rejections"])
    assert page["embed"]["positionCalls"] >= 1, page["embed"]
    assert _overlay(last) == ("Seven cue", False), (last[OVERLAY], page["embed"], page["rejections"])
