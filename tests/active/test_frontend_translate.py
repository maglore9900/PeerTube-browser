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

Generation request, with a key and Translate stored on at load:
- A `none` answer with `available` true is followed by exactly one POST `/api/translate`, sent after that answer, whose JSON body is exactly `{"id": "uuid-1", "host": "peer.example"}` and which carries the stored profile key; the poll then asks twice more and no second POST is sent.
- A `none` answer with `available` false sends no POST, no GET after the first, and reads "No English translation is available for this video.", although a POST would have been answered `queued`; the same scenario with only `available` true sends one POST.

State poll, which follows a job until it ends:
- queued, then running with 2 cues (total 2), then running with 1 more (total 3), then ready: the three poll GETs ask `id=uuid-1&host=peer.example` with `after` 0, 2 and 3. Position 7 shows the running "Seven running"; position 3.5 shows the appended "Three running", which starts before a held cue, so only a re-sorted list finds it; after ready, 3.5 shows nothing (the running cue is gone) and 7 shows "Seven final"; no GET follows ready and no POST is sent.
- A running answer whose `total` (1) is below the 2 cues held makes the next GET ask `after=0`, the GET before it having asked `after=2`.
- failed, after a running answer showed "Seven running" at 7, leaves the overlay empty and hidden, a later 7 still shows nothing, and no GET follows.
- busy, answered to the generation request, reads "The translation queue is full. Turn Translate off and on to try again." and no GET follows the first.
- A poll answered `none`, a poll answered 401, and Translate turned off after the second GET (stored `off`) each leave the GET count at 2.
- A poll answered 502 leaves the status reading "Waiting for translation…" as it did before, and a later GET is still made.

The request and the poll run under a second runner, `GENERATION_RUNNER`, because the first runner (below) serves one fixed answer to every request. It stubs the browser platform the same way; its fetch stub records each request's method, URL, profile key and body, and serves the answers given for its `METHOD path` in turn, repeating the last one; an unconfigured `METHOD path` gets a 500. The poll runs on real timers, so every scenario's page runs at once in its own node process: a `gets` step waits until that many GETs were made, giving up 20 s after the last GET (past the 16 s backoff cap), and a stop is read after a 6.5 s `wait`, past the 2 s (state changed) or 4 s (unchanged, or an error after a change) at which the backoff would schedule the next poll at that point.

The first runner stubs the browser platform as `tests/active/test_frontend_video_page.py` does (recording elements, storages, `fetch`), seeds the toggle with video-page.html's own label, and starts the toggle and overlay hidden, so the page has to set their visibility. `@peertube/embed-api` is aliased at bundle time to a stand-in, because a real player talks to an instance's embed over postMessage and node has no iframe; the stand-in records each construction, the iframe and its src at that moment, and each `getCurrentPosition` call, and its `ready` is created in the constructor as the library's is, then resolved or rejected by the runner after the page has loaded (or left pending, or the constructor throws a string, as jschannel does). Each step clicks an element by id, reports a position to every `playbackStatusUpdate` listener, moves the player without reporting, or waits; the run snapshots the toggle, status and overlay, the stored setting and the request count before `ready` settles, after, and after each step.
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


WAITING = "Waiting for translation\u2026"
BUSY = "The translation queue is full. Turn Translate off and on to try again."
# After a terminal answer the poll would next fire at 2 s (a changed state) or 4 s (unchanged, or an error after a change); waiting past both shows it stopped.
STOP_WAIT = 6500
RUNNING_FIRST = [{"start": 0.25, "end": 1.0, "text": "Zero running"}, {"start": 6.0, "end": 8.0, "text": "Seven running"}]
# Starts before "Seven running", so appended unsorted the binary search misses it at 3.5.
RUNNING_MORE = [{"start": 3.0, "end": 4.0, "text": "Three running"}]
FINAL = [{"start": 0.25, "end": 1.0, "text": "Zero final"}, {"start": 6.0, "end": 8.0, "text": "Seven final"}]

GENERATION_EMBED_STUB = """
// Stands in for @peertube/embed-api: a real player talks to the instance's embed over postMessage, and node has no iframe.
export class PeerTubePlayer {
  constructor(iframe) {
    const state = globalThis.__embedApi;
    this.listeners = {};
    state.players.push(this);
    this.readyPromise = new Promise((resolve) => { state.releases.push(() => resolve()); });
  }
  get ready() { return this.readyPromise; }
  addEventListener(name, handler) { (this.listeners[name] ??= []).push(handler); return true; }
  removeEventListener(name, handler) { this.listeners[name] = (this.listeners[name] ?? []).filter((h) => h !== handler); return true; }
  getCurrentPosition() { return Promise.resolve(globalThis.__embedApi.position); }
}
"""

GENERATION_RUNNER = """
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
const element = (tag, hidden = false) => {
  const classes = new Set();
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), hidden, disabled: false, children: [], dataset: {}, style: {}, attrs: {}, listeners: {}, parentElement: null,
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    get innerText() { return el.textContent; },
    set innerText(v) { el.textContent = v; },
    get innerHTML() { return el.children.map((c) => c.html ?? "").join(""); },
    set innerHTML(v) { el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    get href() { return el.attrs.href ?? ""; },
    set href(v) { el.attrs.href = String(v); },
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
    insertAdjacentHTML() {}, remove() {},
  };
  return el;
};
const initiallyHidden = JSON.parse(process.env.INITIALLY_HIDDEN);
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element(id === "video-embed" ? "iframe" : "div", initiallyHidden.includes(id))); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
const embed = globalThis.__embedApi = { players: [], releases: [], position: null };
const answers = JSON.parse(process.env.ANSWERS);
const requests = [];
let lastGetAt = 0;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  const method = String(init?.method ?? input?.method ?? "GET").toUpperCase();
  if (method === "GET" && url.pathname === "/api/translate") lastGetAt = Date.now();
  requests.push({ method, url: url.href, key: new Headers(init?.headers ?? input?.headers ?? {}).get("x-profile-key"), body: typeof init?.body === "string" ? init.body : null });
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/video") return new Response(process.env.VIDEO_BODY, { status: 200, headers });
  if (url.pathname === "/api/translate") {
    // Answers are served in turn and the last repeats; an unconfigured METHOD path is a 500, so a request the case did not expect cannot read as a valid answer.
    const queue = answers[`${method} ${url.pathname}`];
    if (!queue) return new Response(JSON.stringify({ error: "unexpected request" }), { status: 500, headers });
    const answer = queue.length > 1 ? queue.shift() : queue[0];
    return new Response(JSON.stringify(answer.body), { status: answer.status, headers });
  }
  return new Response("{}", { status: 200, headers });
};
const rejections = [];
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
await import(process.env.BUNDLE);
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
const count = (method) => requests.filter((r) => r.method === method && new URL(r.url).pathname === "/api/translate").length;
const snapshots = [];
const snapshot = () => {
  const overlay = document.getElementById(process.env.OVERLAY);
  snapshots.push({ status: document.getElementById(process.env.STATUS).textContent, overlay: [overlay.textContent, overlay.hidden], toggleHidden: document.getElementById(process.env.TOGGLE).hidden,
    stored: localStorage.getItem("translate:v1"), gets: count("GET"), posts: count("POST") });
};
const click = (el) => {
  if (el.disabled || el.hidden) return false;
  const event = { type: "click", target: el, currentTarget: el, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() {} };
  for (const listener of [...(el.listeners.click ?? [])]) { try { listener.call(el, event); } catch (error) { rejections.push(String(error)); } }
  return true;
};
await settle();
snapshot();
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
  // Waits for the poll to have made this many GETs and records how many it had made; it gives up 20 s after the last GET, past the 16 s backoff cap, so a running poll is never cut off and a page that never polls costs one wait, not one per step.
  if ("gets" in step) {
    while (count("GET") < step.gets && Date.now() - lastGetAt < 20000) await new Promise((resolve) => setTimeout(resolve, 50));
    steps.push(count("GET"));
  }
  if ("wait" in step) { await new Promise((resolve) => setTimeout(resolve, step.wait)); steps.push(true); }
  await settle();
  snapshot();
}
process.stdout.write(JSON.stringify({ requests, snapshots, steps, rejections, title: byId.get("video-title")?.textContent ?? null }) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def generation_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("translate_generation_page")
    (out / "embed-api.mjs").write_text(GENERATION_EMBED_STUB)
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}", f"--alias:@peertube/embed-api={out / 'embed-api.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(GENERATION_RUNNER)
    return out


def _state(state: str, available: bool = True, **extra) -> dict:
    return {"status": 200, "body": {"state": state, "available": available, **extra}}


GENERATION_SCENARIOS = {
    "request": {"gets": [_state("none"), _state("queued")], "posts": [_state("queued")], "steps": [{"gets": 3}]},
    # a POST would be answered queued, so a page that requested anyway would also start polling
    "unavailable": {"gets": [_state("none", available=False)], "posts": [_state("queued")], "steps": [{"wait": STOP_WAIT}]},
    # the unavailable case with only `available` flipped, so its one POST shows this page reads the flag rather than never requesting
    "available": {"gets": [_state("none")], "posts": [_state("queued")], "steps": [{"wait": STOP_WAIT}]},
    "running": {"gets": [_state("queued"), _state("running", cues=RUNNING_FIRST, total=2), _state("running", cues=RUNNING_MORE, total=3), _state("ready", cues=FINAL)],
                "steps": [{"gets": 2}, {"emit": 7}, {"gets": 3}, {"emit": 3.5}, {"gets": 4}, {"emit": 3.5}, {"emit": 7}, {"wait": STOP_WAIT}]},
    "reset": {"gets": [_state("running", cues=RUNNING_FIRST, total=2), _state("running", cues=[], total=1), _state("running", cues=RUNNING_FIRST[:1], total=1)], "steps": [{"gets": 3}]},
    "failed": {"gets": [_state("running", cues=RUNNING_FIRST, total=2), _state("failed")], "steps": [{"emit": 7}, {"gets": 2}, {"emit": 7}, {"wait": STOP_WAIT}]},
    "busy": {"gets": [_state("none")], "posts": [_state("busy")], "steps": [{"wait": STOP_WAIT}]},
    "stop-none": {"gets": [_state("queued"), _state("none")], "steps": [{"gets": 2}, {"wait": STOP_WAIT}]},
    "stop-401": {"gets": [_state("queued"), {"status": 401, "body": {"error": "Profile key required"}}], "steps": [{"gets": 2}, {"wait": STOP_WAIT}]},
    "stop-off": {"gets": [_state("queued")], "steps": [{"gets": 2}, {"click": TOGGLE}, {"wait": STOP_WAIT}]},
    "502": {"gets": [_state("queued"), {"status": 502, "body": {"error": "Engine translate failed"}}, _state("queued")], "steps": [{"gets": 2}, {"gets": 3}]},
}


def _generation_env(bundle: Path, *, gets: list[dict], posts: list[dict] | None = None, steps: list[dict]) -> dict:
    answers = {"GET /api/translate": gets, **({"POST /api/translate": posts} if posts else {})}
    return {"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "HOST": HOST,
            "STORAGE": json.dumps({"profileKey:v1": KEY, "translate:v1": "on"}), "ANSWERS": json.dumps(answers),
            "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, "embedUrl": EMBED, "originalUrl": ORIGINAL}),
            "INITIALLY_HIDDEN": json.dumps([TOGGLE, OVERLAY]), "TOGGLE": TOGGLE, "STATUS": STATUS, "OVERLAY": OVERLAY, "STEPS": json.dumps(steps)}


@pytest.fixture(scope="module")
def generation_pages(generation_bundle) -> dict:
    # Each scenario waits on real timers, so all run at once and the module takes about as long as its slowest one.
    procs = {name: subprocess.Popen(["node", str(generation_bundle / "runner.mjs")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_generation_env(generation_bundle, **scenario)) for name, scenario in GENERATION_SCENARIOS.items()}
    finished = {}
    try:
        for name, proc in procs.items():
            stdout, stderr = proc.communicate(timeout=150)
            finished[name] = (proc.returncode, stdout, stderr)
    finally:
        for proc in procs.values():
            proc.kill()
    return finished


def _generation_page(pages: dict, name: str) -> dict:
    returncode, stdout, stderr = pages[name]
    assert returncode == 0, stderr
    page = json.loads(stdout.splitlines()[-1])
    # control: the page rendered its body, ready resolved into a shown toggle, and the run left a snapshot before ready, one after, and one per step
    assert page["title"] == TITLE, page
    assert page["snapshots"][1]["toggleHidden"] is False, (page["snapshots"], page["rejections"])
    assert len(page["snapshots"]) == len(GENERATION_SCENARIOS[name]["steps"]) + 2, page["snapshots"]
    return page


def _translate_by_method(page: dict, method: str) -> list[dict]:
    return [request for request in page["requests"] if request["method"] == method and urlsplit(request["url"]).path == "/api/translate"]


def _query(request: dict) -> dict:
    return parse_qs(urlsplit(request["url"]).query)


def _asked(page: dict) -> tuple:
    # What a failure prints: the translate requests in order and anything that escaped the page.
    return [(request["method"], request["url"], request["body"]) for request in page["requests"] if urlsplit(request["url"]).path == "/api/translate"], page["rejections"]


def test_a_none_state_from_a_serving_worker_sends_one_generation_request_with_the_video_and_key_and_no_second_while_polled(generation_pages):
    page = _generation_page(generation_pages, "request")
    posts = _translate_by_method(page, "POST")
    first_get = page["requests"].index(_translate_by_method(page, "GET")[0])

    assert len(posts) == 1, _asked(page)
    # the poll asked twice after the request, so the one POST held over several polls rather than only until the run ended
    assert page["steps"] == [3], _asked(page)
    assert json.loads(posts[0]["body"]) == {"id": "uuid-1", "host": HOST}, posts
    assert posts[0]["key"] == KEY, posts
    # sent once the state route answered none, not alongside it
    assert page["requests"].index(posts[0]) > first_get, _asked(page)


def test_a_none_state_without_a_serving_worker_sends_no_request_polls_nothing_and_reads_the_plan_48_message(generation_pages):
    page = _generation_page(generation_pages, "unavailable")
    twin = _generation_page(generation_pages, "available")
    last = page["snapshots"][-1]

    # control: the same stubs and steps with `available` true make this page send its POST, so the empty list below is the flag being read and not a page that never requests
    assert len(_translate_by_method(twin, "POST")) == 1, _asked(twin)
    assert _translate_by_method(page, "POST") == [], _asked(page)
    assert len(_translate_by_method(page, "GET")) == 1, _asked(page)
    assert last["status"] == NO_TRANSLATION, (last, _asked(page))


def test_running_cues_are_asked_for_after_the_held_count_shown_at_their_positions_and_replaced_by_ready_which_ends_the_poll(generation_pages):
    page = _generation_page(generation_pages, "running")
    _, running_7, _, running_3_5, _, ready_3_5, ready_7, _ = page["snapshots"][2:]
    polls = [_query(request) for request in _translate_by_method(page, "GET")[1:]]

    # the poll asked again after queued and after each running answer
    assert [page["steps"][i] for i in (0, 2, 4)] == [2, 3, 4], _asked(page)
    assert polls == [{"id": ["uuid-1"], "host": [HOST], "after": ["0"]}, {"id": ["uuid-1"], "host": [HOST], "after": ["2"]}, {"id": ["uuid-1"], "host": [HOST], "after": ["3"]}], _asked(page)
    assert running_7["overlay"] == ["Seven running", False], (running_7, _asked(page))
    # the appended cue starts before a held one, so only a list re-sorted after the append finds it
    assert running_3_5["overlay"] == ["Three running", False], running_3_5
    # ready replaced the list: the running cue at 3.5 is gone and 7 reads the final cue
    assert ready_3_5["overlay"] == ["", True], ready_3_5
    assert ready_7["overlay"] == ["Seven final", False], ready_7
    assert page["snapshots"][-1]["gets"] == 4, _asked(page)
    assert _translate_by_method(page, "POST") == [], _asked(page)


def test_a_running_total_below_the_held_count_makes_the_next_poll_ask_from_zero(generation_pages):
    page = _generation_page(generation_pages, "reset")

    assert page["steps"] == [3], _asked(page)
    # the poll before the drop asked after the 2 held cues, so the 0 after it is the reset and not a page that always asks 0
    assert [_query(request).get("after") for request in _translate_by_method(page, "GET")[1:3]] == [["2"], ["0"]], _asked(page)


def test_failed_clears_the_overlay_and_its_lines_and_ends_the_poll(generation_pages):
    page = _generation_page(generation_pages, "failed")
    shown, failed, again, last = page["snapshots"][2:]

    # the poll asked again while running, and that second GET was answered failed
    assert page["steps"][1] == 2, _asked(page)
    # control: the running cue showed at 7 before failed arrived
    assert shown["overlay"] == ["Seven running", False], (shown, _asked(page))
    assert failed["overlay"] == ["", True], failed
    # the lines went too, not only the text: 7 still shows nothing
    assert again["overlay"] == ["", True], again
    assert last["gets"] == 2, _asked(page)


def test_busy_shows_its_label_and_is_not_polled(generation_pages):
    page = _generation_page(generation_pages, "busy")
    last = page["snapshots"][-1]

    assert last["status"] == BUSY, (last, _asked(page))
    # control: the generation request was sent, so the busy label answers it
    assert last["posts"] == 1, _asked(page)
    assert last["gets"] == 1, _asked(page)


@pytest.mark.parametrize("case", ["none", "401", "off"])
def test_a_none_answer_a_401_or_turning_translate_off_ends_the_poll(generation_pages, case):
    page = _generation_page(generation_pages, f"stop-{case}")

    assert page["snapshots"][-1]["gets"] == 2, _asked(page)
    # control: the poll was running, a second GET having been made, and a click reached the shown toggle and stored off
    assert page["steps"][0] == 2, _asked(page)
    assert all(page["steps"][1:]), page["steps"]
    if case == "off":
        assert page["snapshots"][-1]["stored"] == "off", page["snapshots"][-1]


def test_a_502_keeps_the_waiting_label_and_the_poll_asks_again(generation_pages):
    page = _generation_page(generation_pages, "502")
    ready, after_502 = page["snapshots"][1], page["snapshots"][2]

    assert page["steps"][1] == 3, _asked(page)
    # control: the label the 502 must keep was showing before it, and the second GET was the one answered 502
    assert ready["status"] == WAITING, (ready, _asked(page))
    assert page["steps"][0] == 2, _asked(page)
    assert after_502["status"] == WAITING, (after_502, _asked(page))
