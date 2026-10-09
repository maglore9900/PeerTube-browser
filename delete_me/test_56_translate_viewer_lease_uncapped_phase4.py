"""Plan 56 phase 4 checkpoint: on the video page, turning Translate off sends exactly one cancel, with the video and the profile key, at once when no state poll is in flight and only after the state poll in flight at the click was answered when one is, and a failed cancel escapes nothing; each poll answering `none` from a serving worker sends a generation request, with the video and the key, after that answer and before the next poll, and once that request is answered and before the next poll the page reads the waiting label, while the same `none` without `available` sends none.

The page runs in node as in the generation_pages scenarios of tests/active/test_frontend_translate.py: the real video page bundled with the embed API stood in, its fetches going to a stub gateway that serves each `METHOD path`'s answers in turn (the last repeating, an unconfigured one a 500). Here the stub also answers `POST /api/translate/cancel` from its own key, holds an answer for its `delay`, records on each request the request count at the moment its answer was returned (`answeredAfter`), and records per click and per snapshot the indices of the requests still unanswered.

Cancel (C1): the second poll is held 1.5 s and the toggle clicked off while it is (that GET listed as held at the click, the setting stored off, and the GET answered afterwards). Exactly one `POST /api/translate/cancel` is sent; its body is exactly `{"id": "uuid-1", "host": "peer.example"}` and it carries the stored key; its index in the requests is at or past the held GET's `answeredAfter`, so it was sent after that answer and not at the click; the cancel is answered 502 and nothing is recorded as an unhandled rejection. In its twin the second poll is answered at once and the toggle clicked off between polls (nothing held at the click, the setting stored off): the one cancel, with the same body and key, is already sent in the snapshot 100 ms after the click, and no GET follows.

Re-request (C2): GETs answer none (available), queued, none (available), queued, none (available), queued, and the generation request answers queued. The first POST precedes the queued poll, so it is turnOn's; exactly three POSTs to `/api/translate` are sent; the second and third each sit at or past their none's `answeredAfter` and before the next GET, have body exactly `{"id": "uuid-1", "host": "peer.example"}` and the stored key; in the snapshot taken once the second POST was sent, with that POST and the three GETs answered and no fourth GET made, the status reads "Waiting for translation…". The twin, cut at the first poll none with that none's `available` false, makes its third GET too, sends turnOn's POST alone, and reads "No English translation is available for this video."
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

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
WAITING = "Waiting for translation\u2026"
TRANSLATE = "/api/translate"
CANCEL = "/api/translate/cancel"
VIDEO = {"id": "uuid-1", "host": HOST}
# After a terminal answer the poll would next fire at 2 s (a changed state) or 4 s (unchanged); waiting past both shows it stopped.
STOP_WAIT = 6500
# The held poll's answer is delayed this long; the click lands about 150 ms after the poll was sent, well inside it.
HELD_MS = 1500

EMBED_STUB = """
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

# GENERATION_RUNNER of tests/active/test_frontend_translate.py, with the cancel path answered from its own key, a per-answer `delay`, each request's `answeredAfter` (the request count when its answer was returned) and, per click, the indices of requests still held.
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
  const record = { method, url: url.href, key: new Headers(init?.headers ?? input?.headers ?? {}).get("x-profile-key"), body: typeof init?.body === "string" ? init.body : null, answeredAfter: null };
  requests.push(record);
  const headers = { "content-type": "application/json" };
  // The answer is returned at this point, so a request recorded at an index at or past answeredAfter was sent after this one was answered.
  const answered = (response) => { record.answeredAfter = requests.length; return response; };
  if (url.pathname === "/api/video") return answered(new Response(process.env.VIDEO_BODY, { status: 200, headers }));
  if (url.pathname === "/api/translate" || url.pathname === "/api/translate/cancel") {
    // Answers are served in turn and the last repeats; an unconfigured METHOD path is a 500, so a request the case did not expect cannot read as a valid answer.
    const queue = answers[`${method} ${url.pathname}`];
    if (!queue) return answered(new Response(JSON.stringify({ error: "unexpected request" }), { status: 500, headers }));
    const answer = queue.length > 1 ? queue.shift() : queue[0];
    if (answer.delay) await new Promise((resolve) => setTimeout(resolve, answer.delay));
    return answered(new Response(JSON.stringify(answer.body), { status: answer.status, headers }));
  }
  return answered(new Response("{}", { status: 200, headers }));
};
const rejections = [];
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
await import(process.env.BUNDLE);
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
const count = (method, path) => requests.filter((r) => r.method === method && new URL(r.url).pathname === path).length;
const snapshots = [];
const snapshot = () => {
  const overlay = document.getElementById(process.env.OVERLAY);
  snapshots.push({ status: document.getElementById(process.env.STATUS).textContent, overlay: [overlay.textContent, overlay.hidden], toggleHidden: document.getElementById(process.env.TOGGLE).hidden,
    stored: localStorage.getItem("translate:v1"), gets: count("GET", "/api/translate"), posts: count("POST", "/api/translate"), cancels: count("POST", "/api/translate/cancel"), held: held() });
};
const click = (el) => {
  if (el.disabled || el.hidden) return false;
  const event = { type: "click", target: el, currentTarget: el, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() {} };
  for (const listener of [...(el.listeners.click ?? [])]) { try { listener.call(el, event); } catch (error) { rejections.push(String(error)); } }
  return true;
};
const held = () => requests.flatMap((r, i) => (r.answeredAfter === null ? [i] : []));
await settle();
snapshot();
embed.releases.forEach((release) => release());
await settle();
snapshot();
const steps = [];
for (const step of JSON.parse(process.env.STEPS)) {
  // The requests still unanswered when the click reached the toggle, read before the click so nothing it sends is among them.
  if ("click" in step) { const before = held(); steps.push(click(document.getElementById(step.click)) ? { held: before } : false); }
  // Waits for the poll to have made this many GETs and records how many it had made; it gives up 20 s after the last GET, past the 16 s backoff cap.
  if ("gets" in step) {
    while (count("GET", "/api/translate") < step.gets && Date.now() - lastGetAt < 20000) await new Promise((resolve) => setTimeout(resolve, 50));
    steps.push(count("GET", "/api/translate"));
  }
  // The same wait on generation requests, with the same give-up.
  if ("posts" in step) {
    while (count("POST", "/api/translate") < step.posts && Date.now() - lastGetAt < 20000) await new Promise((resolve) => setTimeout(resolve, 50));
    steps.push(count("POST", "/api/translate"));
  }
  if ("wait" in step) { await new Promise((resolve) => setTimeout(resolve, step.wait)); steps.push(true); }
  await settle();
  snapshot();
}
process.stdout.write(JSON.stringify({ requests, snapshots, steps, rejections, title: byId.get("video-title")?.textContent ?? null }) + "\\n", () => process.exit(0));
"""


def _state(state: str, available: bool = True, **extra) -> dict:
    return {"status": 200, "body": {"state": state, "available": available, **extra}}


SCENARIOS = {
    # The second poll is held HELD_MS and the toggle is clicked off while it is; the cancel is answered 502, so a cancel left uncaught surfaces as a rejection.
    "cancel-held": {"answers": {f"GET {TRANSLATE}": [_state("queued"), {**_state("queued"), "delay": HELD_MS}], f"POST {CANCEL}": [{"status": 502, "body": {"error": "Engine translate failed"}}]},
                    "steps": [{"gets": 2}, {"click": TOGGLE}, {"wait": 2 * HELD_MS}]},
    # The second poll is answered at once and the toggle is clicked off before the next one is due, so no poll is in flight at the click.
    "cancel-idle": {"answers": {f"GET {TRANSLATE}": [_state("queued")], f"POST {CANCEL}": [{"status": 502, "body": {"error": "Engine translate failed"}}]},
                    "steps": [{"gets": 2}, {"click": TOGGLE}, {"wait": 2 * HELD_MS}]},
    # turnOn's none asks once; the poll then reads queued and none from a serving worker twice over. The first step snapshots the page once the poll's first re-request is sent, before the next poll.
    "re-request": {"answers": {f"GET {TRANSLATE}": [_state("none"), _state("queued"), _state("none"), _state("queued"), _state("none"), _state("queued")], f"POST {TRANSLATE}": [_state("queued")]},
                   "steps": [{"posts": 2}, {"gets": 5}, {"wait": STOP_WAIT}]},
    # The re-request case cut at its first poll none, with that none's `available` flipped.
    "re-request-unavailable": {"answers": {f"GET {TRANSLATE}": [_state("none"), _state("queued"), _state("none", available=False)], f"POST {TRANSLATE}": [_state("queued")]},
                               "steps": [{"gets": 3}, {"wait": STOP_WAIT}]},
}


def _bundle(out: Path, src: Path) -> Path:
    (out / "embed-api.mjs").write_text(EMBED_STUB)
    subprocess.run(
        [str(ESBUILD), str(src / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}", f"--alias:@peertube/embed-api={out / 'embed-api.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _env(bundle: Path, *, answers: dict, steps: list[dict]) -> dict:
    return {"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "HOST": HOST,
            "STORAGE": json.dumps({"profileKey:v1": KEY, "translate:v1": "on"}), "ANSWERS": json.dumps(answers),
            "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, "embedUrl": EMBED, "originalUrl": ORIGINAL}),
            "INITIALLY_HIDDEN": json.dumps([TOGGLE, OVERLAY]), "TOGGLE": TOGGLE, "STATUS": STATUS, "OVERLAY": OVERLAY, "STEPS": json.dumps(steps)}


def _run(bundle: Path) -> dict:
    # Each scenario waits on real timers, so all run at once.
    procs = {name: subprocess.Popen(["node", str(bundle / "runner.mjs")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env(bundle, **scenario)) for name, scenario in SCENARIOS.items()}
    finished = {}
    try:
        for name, proc in procs.items():
            stdout, stderr = proc.communicate(timeout=150)
            finished[name] = (proc.returncode, stdout, stderr)
    finally:
        for proc in procs.values():
            proc.kill()
    return finished


@pytest.fixture(scope="module")
def pages(tmp_path_factory) -> dict:
    return _run(_bundle(tmp_path_factory.mktemp("translate_phase4"), FRONTEND / "src"))


def _page(pages: dict, name: str) -> dict:
    returncode, stdout, stderr = pages[name]
    assert returncode == 0, stderr
    page = json.loads(stdout.splitlines()[-1])
    # control: the page rendered its body, ready resolved into a shown toggle, and the run left a snapshot before ready, one after, and one per step
    assert page["title"] == TITLE, page
    assert page["snapshots"][1]["toggleHidden"] is False, (page["snapshots"], page["rejections"])
    assert len(page["snapshots"]) == len(SCENARIOS[name]["steps"]) + 2, page["snapshots"]
    return page


def _indexed(page: dict, method: str, path: str) -> list[tuple[int, dict]]:
    # (index in page["requests"], request), so order is read by position and two equal records cannot be confused.
    return [(i, request) for i, request in enumerate(page["requests"]) if request["method"] == method and urlsplit(request["url"]).path == path]


def _asked(page: dict) -> tuple:
    # What a failure prints: the translate and cancel requests in order, with where each was answered, and anything that escaped the page.
    return [(i, request["method"], request["url"], request["body"], request["answeredAfter"]) for i, request in enumerate(page["requests"]) if urlsplit(request["url"]).path in (TRANSLATE, CANCEL)], page["rejections"]


def test_turning_translate_off_during_a_held_poll_sends_one_cancel_with_the_video_and_key_only_after_that_poll_answered(pages):
    page = _page(pages, "cancel-held")
    gets = _indexed(page, "GET", TRANSLATE)
    cancels = _indexed(page, "POST", CANCEL)

    # control: the second GET was made, was still held when the click reached the shown toggle, which stored off, and was answered later
    assert page["steps"][0] == 2, _asked(page)
    held_index, held_get = gets[1]
    assert page["steps"][1] == {"held": [held_index]}, (page["steps"], _asked(page))
    assert page["snapshots"][3]["stored"] == "off", page["snapshots"][3]
    assert held_get["answeredAfter"] is not None, _asked(page)
    assert len(cancels) == 1, _asked(page)  # C1
    cancel_index, cancel = cancels[0]
    assert json.loads(cancel["body"]) == VIDEO, cancel  # C1
    assert cancel["key"] == KEY, cancel  # C1
    # sent once the held poll was answered, not at the click while it was still in flight
    assert cancel_index >= held_get["answeredAfter"], _asked(page)  # C1
    # control: the cancel's 502 was returned to the page before the run ended, so a cancel without its own catch would be recorded below
    assert cancel["answeredAfter"] is not None, _asked(page)
    assert page["rejections"] == [], page["rejections"]  # C1


def test_turning_translate_off_between_polls_sends_one_cancel_with_the_video_and_key_at_once(pages):
    page = _page(pages, "cancel-idle")
    cancels = _indexed(page, "POST", CANCEL)

    # control: the second GET was made and answered, nothing was held when the click reached the shown toggle, and the click stored off
    assert page["steps"][0] == 2, _asked(page)
    assert page["steps"][1] == {"held": []}, (page["steps"], _asked(page))
    assert page["snapshots"][3]["stored"] == "off", page["snapshots"][3]
    # with no poll to wait on, the cancel is out by the snapshot taken 100 ms after the click, not on a later timer or a later poll's answer
    assert page["snapshots"][3]["cancels"] == 1, (page["snapshots"][3], _asked(page))  # C1
    assert len(cancels) == 1, _asked(page)  # C1
    cancel = cancels[0][1]
    assert json.loads(cancel["body"]) == VIDEO, cancel  # C1
    assert cancel["key"] == KEY, cancel  # C1
    # control: off stopped the poll, so no GET followed the second, and the cancel's 502 was returned to the page before the run ended
    assert page["snapshots"][-1]["gets"] == 2, _asked(page)
    assert cancel["answeredAfter"] is not None, _asked(page)
    assert page["rejections"] == [], page["rejections"]  # C1


def test_a_poll_reading_none_from_a_serving_worker_requests_generation_again_each_time_with_the_video_and_key_and_shows_waiting_and_one_without_does_not(pages):
    page = _page(pages, "re-request")
    twin = _page(pages, "re-request-unavailable")
    gets = _indexed(page, "GET", TRANSLATE)
    posts = _indexed(page, "POST", TRANSLATE)

    # control: both pages made their third GET, the first poll answered none
    assert len(gets) >= 3, _asked(page)
    assert twin["steps"][0] == 3, _asked(twin)
    # control: the first POST is turnOn's, sent before the poll's queued, so the rest are the poll's
    assert posts[0][0] < gets[1][0], _asked(page)
    assert len(posts) == 3, _asked(page)  # C2
    # control: the page made the GET after the second poll none, so each re-request is bounded by the next poll
    assert len(gets) >= 6, _asked(page)
    # each re-request was sent after its none was answered and before the next poll asked, so the two nones sent one each
    for (post_index, post), (_, none_get), (next_index, _) in zip(posts[1:], (gets[2], gets[4]), (gets[3], gets[5])):
        assert none_get["answeredAfter"] <= post_index < next_index, _asked(page)  # C2
        assert json.loads(post["body"]) == VIDEO, post  # C2
        assert post["key"] == KEY, post  # C2
    # control: the snapshot after the first step was taken with the poll's first re-request sent and answered, the none GET before it answered, and no fourth GET made, so no later queued poll set the label
    rerequested = page["snapshots"][2]
    assert page["steps"][0] == 2, _asked(page)
    assert (rerequested["posts"], rerequested["gets"], rerequested["held"]) == (2, 3, []), (rerequested, _asked(page))
    assert rerequested["status"] == WAITING, (rerequested, _asked(page))  # C2
    # the same answers up to the first poll none, with that none's available false: turnOn's POST alone
    assert len(_indexed(twin, "POST", TRANSLATE)) == 1, _asked(twin)  # C2
    # control: the twin's none ended its poll as before, so its single POST is the flag read and not a none the twin never reached
    assert twin["snapshots"][-1]["status"] == NO_TRANSLATION, (twin["snapshots"][-1], _asked(twin))
