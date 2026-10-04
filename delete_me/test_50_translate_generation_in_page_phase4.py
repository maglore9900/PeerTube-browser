"""Phase 4 checkpoint of plan 50: the video page, bundled and run in node with Translate stored on and a profile key held, asks for generation once and follows the job with its state poll.

Request (C1):
- A `none` answer with `available` true is followed by exactly one POST `/api/translate`, sent after that answer, whose JSON body is exactly `{"id": "uuid-1", "host": "peer.example"}` and which carries the stored profile key; the poll then asks twice more and no second POST is sent.
- A `none` answer with `available` false sends no POST, no GET after the first, and reads plan 48's "No English translation is available for this video.", although a POST would have been answered `queued`; the same scenario with only `available` true sends one POST.

State poll (C2):
- queued, then running with 2 cues (total 2), then running with 1 more (total 3), then ready: the three poll GETs ask `id=uuid-1&host=peer.example` with `after` 0, 2 and 3. Position 7 shows the running "Seven running"; position 3.5 shows the appended "Three running", which starts before a held cue, so only a re-sorted list finds it; after ready, 3.5 shows nothing (the running cue is gone) and 7 shows "Seven final"; no GET follows ready and no POST is sent.
- A running answer whose `total` (1) is below the 2 cues held makes the next GET ask `after=0`, the GET before it having asked `after=2`.
- failed, after a running answer showed "Seven running" at 7, leaves the overlay empty and hidden, a later 7 still shows nothing, and no GET follows.
- busy, answered to the generation request, reads "The translation queue is full. Turn Translate off and on to try again." and no GET follows the first.
- A poll answered `none`, a poll answered 401, and Translate turned off after the second GET (stored `off`) each leave the GET count at 2.
- A poll answered 502 leaves the status reading "Waiting for translation…" as it did before, and a later GET is still made.

The runner stubs the browser platform as `tests/active/test_frontend_translate.py` does. Its fetch stub records each request's method, URL, profile key and body, and serves the answers given for its `METHOD path` in turn, repeating the last one; an unconfigured `METHOD path` gets a 500. `@peertube/embed-api` is aliased at bundle time to a stand-in whose `ready` the runner resolves after load. The poll runs on real timers, so every scenario's page runs at once in its own node process: a `gets` step waits until that many GETs were made, giving up 20 s after the last GET (past the plan's 16 s backoff cap), and a stop is read after a 6.5 s `wait`, past the 2 s (state changed) or 4 s (unchanged, or an error after a change) at which the plan's backoff would schedule the next poll at that point.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
HOST = "peer.example"
TITLE = "Translate generation fixture title"
EMBED = "https://peer.example/videos/embed/uuid-1"
KEY = "translate-profile-key"
TOGGLE = "translate-toggle"
STATUS = "translate-status"
OVERLAY = "translate-overlay"
NO_TRANSLATION = "No English translation is available for this video."
WAITING = "Waiting for translation\u2026"
BUSY = "The translation queue is full. Turn Translate off and on to try again."
# After a terminal answer the plan's poll would next fire at 2 s (a changed state) or 4 s (unchanged, or an error after a change); waiting past both shows it stopped.
STOP_WAIT = 6500
RUNNING_FIRST = [{"start": 0.25, "end": 1.0, "text": "Zero running"}, {"start": 6.0, "end": 8.0, "text": "Seven running"}]
# Starts before "Seven running", so appended unsorted the binary search misses it at 3.5.
RUNNING_MORE = [{"start": 3.0, "end": 4.0, "text": "Three running"}]
FINAL = [{"start": 0.25, "end": 1.0, "text": "Zero final"}, {"start": 6.0, "end": 8.0, "text": "Seven final"}]

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
  // Waits for the poll to have made this many GETs and records how many it had made; it gives up 20 s after the last GET, past the plan's 16 s backoff cap, so a running poll is never cut off and a page that never polls costs one wait, not one per step.
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
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("translate_generation_page")
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


def _state(state: str, available: bool = True, **extra) -> dict:
    return {"status": 200, "body": {"state": state, "available": available, **extra}}


SCENARIOS = {
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


def _env(bundle: Path, *, gets: list[dict], posts: list[dict] | None = None, steps: list[dict]) -> dict:
    answers = {"GET /api/translate": gets, **({"POST /api/translate": posts} if posts else {})}
    return {"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "HOST": HOST,
            "STORAGE": json.dumps({"profileKey:v1": KEY, "translate:v1": "on"}), "ANSWERS": json.dumps(answers),
            "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, "embedUrl": EMBED, "originalUrl": "https://peer.example/videos/watch/uuid-1"}),
            "INITIALLY_HIDDEN": json.dumps([TOGGLE, OVERLAY]), "TOGGLE": TOGGLE, "STATUS": STATUS, "OVERLAY": OVERLAY, "STEPS": json.dumps(steps)}


@pytest.fixture(scope="module")
def pages(bundle) -> dict:
    # Each scenario waits on real timers, so all run at once and the module takes about as long as its slowest one.
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


def _page(pages: dict, name: str) -> dict:
    returncode, stdout, stderr = pages[name]
    assert returncode == 0, stderr
    page = json.loads(stdout.splitlines()[-1])
    # control: the page rendered its body, ready resolved into a shown toggle, and the run left a snapshot before ready, one after, and one per step
    assert page["title"] == TITLE, page
    assert page["snapshots"][1]["toggleHidden"] is False, (page["snapshots"], page["rejections"])
    assert len(page["snapshots"]) == len(SCENARIOS[name]["steps"]) + 2, page["snapshots"]
    return page


def _translate(page: dict, method: str) -> list[dict]:
    return [request for request in page["requests"] if request["method"] == method and urlsplit(request["url"]).path == "/api/translate"]


def _query(request: dict) -> dict:
    return parse_qs(urlsplit(request["url"]).query)


def _asked(page: dict) -> tuple:
    # What a failure prints: the translate requests in order and anything that escaped the page.
    return [(request["method"], request["url"], request["body"]) for request in page["requests"] if urlsplit(request["url"]).path == "/api/translate"], page["rejections"]


def test_a_none_state_from_a_serving_worker_sends_one_generation_request_with_the_video_and_key_and_no_second_while_polled(pages):
    page = _page(pages, "request")
    posts = _translate(page, "POST")
    first_get = page["requests"].index(_translate(page, "GET")[0])

    assert len(posts) == 1, _asked(page)  # C1
    # the poll asked twice after the request, so the one POST held over several polls rather than only until the run ended
    assert page["steps"] == [3], _asked(page)  # C1
    assert json.loads(posts[0]["body"]) == {"id": "uuid-1", "host": HOST}, posts  # C1
    assert posts[0]["key"] == KEY, posts  # C1
    # sent once the state route answered none, not alongside it
    assert page["requests"].index(posts[0]) > first_get, _asked(page)  # C1


def test_a_none_state_without_a_serving_worker_sends_no_request_polls_nothing_and_reads_the_plan_48_message(pages):
    page = _page(pages, "unavailable")
    twin = _page(pages, "available")
    last = page["snapshots"][-1]

    # control: the same stubs and steps with `available` true make this page send its POST, so the empty list below is the flag being read and not a page that never requests
    assert len(_translate(twin, "POST")) == 1, _asked(twin)
    assert _translate(page, "POST") == [], _asked(page)  # C1
    assert len(_translate(page, "GET")) == 1, _asked(page)  # C1
    assert last["status"] == NO_TRANSLATION, (last, _asked(page))  # C1


def test_running_cues_are_asked_for_after_the_held_count_shown_at_their_positions_and_replaced_by_ready_which_ends_the_poll(pages):
    page = _page(pages, "running")
    _, running_7, _, running_3_5, _, ready_3_5, ready_7, _ = page["snapshots"][2:]
    polls = [_query(request) for request in _translate(page, "GET")[1:]]

    # the poll asked again after queued and after each running answer
    assert [page["steps"][i] for i in (0, 2, 4)] == [2, 3, 4], _asked(page)  # C2
    assert polls == [{"id": ["uuid-1"], "host": [HOST], "after": ["0"]}, {"id": ["uuid-1"], "host": [HOST], "after": ["2"]}, {"id": ["uuid-1"], "host": [HOST], "after": ["3"]}], _asked(page)  # C2
    assert running_7["overlay"] == ["Seven running", False], (running_7, _asked(page))  # C2
    # the appended cue starts before a held one, so only a list re-sorted after the append finds it
    assert running_3_5["overlay"] == ["Three running", False], running_3_5  # C2
    # ready replaced the list: the running cue at 3.5 is gone and 7 reads the final cue
    assert ready_3_5["overlay"] == ["", True], ready_3_5  # C2
    assert ready_7["overlay"] == ["Seven final", False], ready_7  # C2
    assert page["snapshots"][-1]["gets"] == 4, _asked(page)  # C2
    assert _translate(page, "POST") == [], _asked(page)


def test_a_running_total_below_the_held_count_makes_the_next_poll_ask_from_zero(pages):
    page = _page(pages, "reset")

    assert page["steps"] == [3], _asked(page)  # C2
    # the poll before the drop asked after the 2 held cues, so the 0 after it is the reset and not a page that always asks 0
    assert [_query(request).get("after") for request in _translate(page, "GET")[1:3]] == [["2"], ["0"]], _asked(page)  # C2


def test_failed_clears_the_overlay_and_its_lines_and_ends_the_poll(pages):
    page = _page(pages, "failed")
    shown, failed, again, last = page["snapshots"][2:]

    # the poll asked again while running, and that second GET was answered failed
    assert page["steps"][1] == 2, _asked(page)  # C2
    # control: the running cue showed at 7 before failed arrived
    assert shown["overlay"] == ["Seven running", False], (shown, _asked(page))
    assert failed["overlay"] == ["", True], failed  # C2
    # the lines went too, not only the text: 7 still shows nothing
    assert again["overlay"] == ["", True], again  # C2
    assert last["gets"] == 2, _asked(page)  # C2


def test_busy_shows_its_label_and_is_not_polled(pages):
    page = _page(pages, "busy")
    last = page["snapshots"][-1]

    assert last["status"] == BUSY, (last, _asked(page))  # C2
    # control: the generation request was sent, so the busy label answers it
    assert last["posts"] == 1, _asked(page)
    assert last["gets"] == 1, _asked(page)  # C2


@pytest.mark.parametrize("case", ["none", "401", "off"])
def test_a_none_answer_a_401_or_turning_translate_off_ends_the_poll(pages, case):
    page = _page(pages, f"stop-{case}")

    assert page["snapshots"][-1]["gets"] == 2, _asked(page)  # C2
    # control: the poll was running, a second GET having been made, and a click reached the shown toggle and stored off
    assert page["steps"][0] == 2, _asked(page)
    assert all(page["steps"][1:]), page["steps"]
    if case == "off":
        assert page["snapshots"][-1]["stored"] == "off", page["snapshots"][-1]


def test_a_502_keeps_the_waiting_label_and_the_poll_asks_again(pages):
    page = _page(pages, "502")
    ready, after_502 = page["snapshots"][1], page["snapshots"][2]

    assert page["steps"][1] == 3, _asked(page)  # C2
    # control: the label the 502 must keep was showing before it, and the second GET was the one answered 502
    assert ready["status"] == WAITING, (ready, _asked(page))
    assert page["steps"][0] == 2, _asked(page)
    assert after_502["status"] == WAITING, (after_502, _asked(page))  # C2
