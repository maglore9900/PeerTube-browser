"""The video page script (`src/pages/video-page/index.ts`) driving `#description-toggle`, run in node.

- A description whose text is taller than four lines at load shows the toggle. One that starts at one
  line shows none, still none when the width makes it exactly four lines, shows it at five, and hides
  it again when the width brings it back to one line. An expanded description made taller by a
  narrower width keeps the toggle, and loses it once a wider width brings it to three lines.
- The placeholder never shows the toggle, even at a width where it is five lines tall; a real
  description with the same geometry does.
- The toggle starts on four lines with "Show more" and aria-expanded="false"; activating it shows
  every line with "Show less" and aria-expanded="true", and activating it again returns to four
  lines, "Show more" and "false". The description keeps the whole text throughout.

The DOM, `getComputedStyle`, `ResizeObserver`, `fetch` and `window` are the browser platform node lacks;
the runner supplies them. Layout is a model, not a browser: the test sets how many lines the full text
takes at each width, and the model reports heights for that text from constants copied by hand from
video.css, collapsed (padding moved into the border, clamped to four lines) or not. Nothing here reads
video.css, so the model does not follow an edit to it: that the constants still match the stylesheet,
and that real CSS yields those heights, stay the maintainer's browser check.
"""
from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
SCRIPT = FRONTEND / "src" / "pages" / "video-page" / "index.ts"
PAGE = FRONTEND / "video-page.html"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
PLACEHOLDER = "No description available."
LONG = "Recorded live at the spring meetup.\n\nChapters:\n0:00 Intro\n3:12 Setup\n10:40 Demo\n25:03 Questions\n\nSlides and code are linked on the instance."
SHORT = "A short talk about federated video."

RUNNER = """
const markup = JSON.parse(process.env.MARKUP);
const LINE = 23.2;  // 16px at line-height 1.45
const layout = { width: 800, lines: 1 };
const htmlWrites = [];
const say = (obj) => process.stdout.write("STATE " + JSON.stringify(obj) + "\\n");

class El {
  constructor(spec = { attrs: {}, text: "" }) {
    this.attrs = new Map(Object.entries(spec.attrs));
    this.text = spec.text;
    this.listeners = new Map();
    this.style = { display: "" };
    this.dataset = {};
  }
  get id() { return this.attrs.get("id") ?? ""; }
  get textContent() { return this.text; }
  set textContent(value) { this.text = String(value ?? ""); }
  get innerText() { return this.text; }
  set innerText(value) { this.text = String(value ?? ""); }
  get innerHTML() { return this.text; }
  set innerHTML(value) { htmlWrites.push(this.id); this.text = String(value).replace(/<[^>]*>/g, ""); }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  removeAttribute(name) { this.attrs.delete(name); }
  hasAttribute(name) { return this.attrs.has(name); }
  toggleAttribute(name, force) {
    const on = force === undefined ? !this.attrs.has(name) : Boolean(force);
    if (on) this.attrs.set(name, ""); else this.attrs.delete(name);
    return on;
  }
  get hidden() { return this.attrs.has("hidden"); }
  set hidden(value) { this.toggleAttribute("hidden", Boolean(value)); }
  get ariaExpanded() { return this.getAttribute("aria-expanded"); }
  set ariaExpanded(value) { this.setAttribute("aria-expanded", value); }
  get className() { return this.attrs.get("class") ?? ""; }
  set className(value) { this.attrs.set("class", String(value)); }
  get classList() {
    const read = () => this.className.split(/\\s+/).filter(Boolean);
    const write = (names) => { this.className = names.join(" "); };
    return {
      contains: (name) => read().includes(name),
      add: (...names) => write([...new Set([...read(), ...names])]),
      remove: (...names) => write(read().filter((n) => !names.includes(n))),
      toggle: (name, force) => {
        const on = force === undefined ? !read().includes(name) : Boolean(force);
        write(on ? [...new Set([...read(), name])] : read().filter((n) => n !== name));
        return on;
      },
    };
  }
  addEventListener(type, fn) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]); }
  removeEventListener(type, fn) { this.listeners.set(type, (this.listeners.get(type) ?? []).filter((f) => f !== fn)); }
  dispatchEvent(event) { fire(this, event.type); return true; }
  click() { fire(this, "click"); }
  closest() { return null; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  insertAdjacentHTML() {}
  replaceChildren() {}
  append() {}
  appendChild(child) { return child; }
  focus() {}
  blur() {}
}

const description = new El(markup["video-description"]);
const toggle = new El(markup["description-toggle"]);
const documentEl = new El();
const windowEl = new El();

// An event reaches its target, then bubbles to document and window.
function fire(target, type) {
  const event = { type, target, currentTarget: target, bubbles: true, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; } };
  for (const node of target === windowEl ? [windowEl] : [target, documentEl, windowEl]) {
    event.currentTarget = node;
    if (typeof node["on" + type] === "function") node["on" + type](event);
    for (const fn of [...(node.listeners.get(type) ?? [])]) fn.call(node, event);
    if (event.stopped) break;
  }
}

// video.css: collapsed moves the 0.8rem 1rem padding into the border and clamps to 4 lines; expanded is that padding and a 1px border.
const collapsed = () => description.classList.contains("description-collapsed");
const box = () => (collapsed() ? { padY: 0, padX: 0, borderY: 13.8, borderX: 17 } : { padY: 12.8, padX: 16, borderY: 1, borderX: 1 });
const textHeight = () => layout.lines * LINE;
const shownHeight = () => (collapsed() ? Math.min(textHeight(), 4 * LINE) : textHeight());
const outerHeight = () => shownHeight() + 2 * box().padY + 2 * box().borderY;
Object.defineProperties(description, {
  scrollHeight: { get: () => Math.round(textHeight() + 2 * box().padY) },
  clientHeight: { get: () => Math.round(shownHeight() + 2 * box().padY) },
  offsetHeight: { get: () => Math.round(outerHeight()) },
  scrollWidth: { get: () => Math.round(layout.width - 2 * box().borderX) },
  clientWidth: { get: () => Math.round(layout.width - 2 * box().borderX) },
  offsetWidth: { get: () => layout.width },
});
description.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: layout.width, height: outerHeight(), right: layout.width, bottom: outerHeight() });
description.getClientRects = () => [description.getBoundingClientRect()];

const px = (n) => `${n}px`;
function getComputedStyle(el) {
  const b = box();
  const values = el === description
    ? { display: collapsed() ? "-webkit-box" : "block", lineHeight: px(LINE), fontSize: "16px", whiteSpace: "pre-wrap",
        boxSizing: "border-box", overflow: collapsed() ? "hidden" : "visible", webkitLineClamp: collapsed() ? "4" : "none",
        paddingTop: px(b.padY), paddingBottom: px(b.padY), paddingLeft: px(b.padX), paddingRight: px(b.padX),
        borderTopWidth: px(b.borderY), borderBottomWidth: px(b.borderY), borderLeftWidth: px(b.borderX), borderRightWidth: px(b.borderX),
        height: px(outerHeight()), width: px(layout.width), maxHeight: "none" }
    : { display: el.hidden ? "none" : el.style.display || "block", lineHeight: "normal", fontSize: "16px" };
  return { ...values, getPropertyValue: (name) => values[name.replace(/-([a-z])/g, (_m, c) => c.toUpperCase())] ?? "" };
}

const observers = [];
const sizeOf = (el) => (el === description ? `${layout.width}x${description.offsetHeight}` : `${layout.width}`);
const entryFor = (el) => {
  const rect = el === description ? description.getBoundingClientRect() : { width: layout.width, height: 0 };
  const size = [{ inlineSize: rect.width, blockSize: rect.height }];
  return { target: el, contentRect: rect, borderBoxSize: size, contentBoxSize: size, devicePixelContentBoxSize: size };
};
globalThis.ResizeObserver = class {
  constructor(callback) { this.callback = callback; this.seen = new Map(); observers.push(this); }
  observe(target) { this.seen.set(target, null); }
  unobserve(target) { this.seen.delete(target); }
  disconnect() { this.seen.clear(); }
};
// Like a browser after layout: each observer hears about the targets whose size changed since it last did, the first time included.
function deliver() {
  for (const observer of observers) {
    const entries = [];
    for (const [target, last] of observer.seen) {
      const now = sizeOf(target);
      if (now !== last) { observer.seen.set(target, now); entries.push(entryFor(target)); }
    }
    if (entries.length) observer.callback(entries, observer);
  }
}

const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
Object.assign(documentEl, {
  title: "", readyState: "complete", body: new El(), documentElement: new El(),
  getElementById: (id) => ({ "video-description": description, "description-toggle": toggle })[id] ?? null,
  createElement: () => new El(),
});
Object.assign(windowEl, {
  location: { origin: process.env.BASE, search: "?id=0f3c2a9e-8d4b-4c1e-9a7f-2b6d5e8c1a40&host=videos.example.org",
    href: process.env.BASE + "/video-page.html" },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage,
  getComputedStyle, devicePixelRatio: 1,
  requestAnimationFrame: (cb) => setTimeout(() => cb(Date.now()), 0), cancelAnimationFrame: (id) => clearTimeout(id),
});
Object.defineProperty(windowEl, "innerWidth", { get: () => layout.width + 400 });
globalThis.window = windowEl;
globalThis.document = documentEl;
globalThis.getComputedStyle = getComputedStyle;
globalThis.requestAnimationFrame = windowEl.requestAnimationFrame;
globalThis.cancelAnimationFrame = windowEl.cancelAnimationFrame;
globalThis.HTMLElement = El;
globalThis.HTMLButtonElement = El;
const respond = (status, body) => ({ ok: status < 300, status, json: async () => body, text: async () => JSON.stringify(body) });
globalThis.fetch = async (url) => (String(url).startsWith(process.env.BASE + "/api/video?")
  ? respond(200, { videoUuid: "0f3c2a9e-8d4b-4c1e-9a7f-2b6d5e8c1a40", title: "A talk", description: process.env.DESCRIPTION })
  : respond(404, {}));

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
async function settle() {
  for (let i = 0; i < 10; i++) { await tick(); deliver(); }
  await new Promise((resolve) => setTimeout(resolve, 200));
  for (let i = 0; i < 10; i++) { await tick(); deliver(); }
}

for (const step of JSON.parse(process.env.STEPS)) {
  const [name, a, b] = step.split("|");
  if (name === "load") { layout.lines = Number(a); await import(process.env.BUNDLE); }
  if (name === "resize") { layout.width = Number(a); layout.lines = Number(b); fire(windowEl, "resize"); }
  if (name === "click") toggle.click();
  await settle();
  say({
    visible: !toggle.hidden && toggle.style.display !== "none",
    label: toggle.textContent.trim(),
    expanded: toggle.getAttribute("aria-expanded"),
    shown: Math.round(shownHeight() / LINE),
    text: description.textContent,
  });
}
process.exit(0);
"""


class _Markup(HTMLParser):
    """The attributes and text video-page.html gives the description and its toggle."""

    def __init__(self):
        super().__init__()
        self.elements: dict[str, dict] = {}
        self._open: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") in ("video-description", "description-toggle"):
            self._open = attrs["id"]
            self.elements[self._open] = {"attrs": {k: v or "" for k, v in attrs.items()}, "text": ""}

    def handle_endtag(self, tag):
        self._open = None

    def handle_data(self, data):
        if self._open:
            self.elements[self._open]["text"] += data


def _bundle(out: Path) -> Path:
    """Bundle the page script with its runner."""
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(ESBUILD), "--bundle", "--format=esm", "--platform=node", "--loader=ts", "--loader:.css=empty",
         "--sourcefile=index.ts", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        input=SCRIPT.read_text(), cwd=SCRIPT.parent, check=True, capture_output=True, text=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _run(bundle: Path, description: str, steps: list[str]) -> list[dict]:
    """Load the page with `description` and report the toggle and description after each step."""
    markup = _Markup()
    markup.feed(PAGE.read_text())
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", ""), "BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"),
             "MARKUP": json.dumps(markup.elements), "DESCRIPTION": description, "STEPS": json.dumps(steps)},
    )
    assert proc.returncode == 0, proc.stderr
    states = [json.loads(line[len("STATE "):]) for line in proc.stdout.splitlines() if line.startswith("STATE ")]
    assert len(states) == len(steps), (proc.stdout, proc.stderr)
    return states


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    return _bundle(tmp_path_factory.mktemp("video-page"))


def test_the_toggle_shows_exactly_while_the_description_is_taller_than_four_lines_at_the_current_width(bundle):
    (tall,) = _run(bundle, LONG, ["load|6"])
    assert tall["visible"] is True, tall  # C1: six lines at load

    loaded, four, five, wide = _run(bundle, SHORT, ["load|1", "resize|500|4", "resize|300|5", "resize|800|1"])
    assert loaded["visible"] is False, loaded  # C1
    assert four["visible"] is False, four  # C1: exactly four lines is not taller than four
    assert five["visible"] is True, five  # C1: a narrower width wraps it to five, with no line break in the text
    assert wide["visible"] is False, wide  # C1: widening back to one line hides it again

    _loaded, expanded, narrower, wider = _run(bundle, LONG, ["load|6", "click", "resize|500|8", "resize|1400|3"])
    assert expanded["shown"] == 6, expanded  # control: the next resize measures an expanded description
    assert narrower["visible"] is True, narrower  # C1: expanded and eight lines tall still shows it
    assert narrower["shown"] == 8, narrower  # C2: expanded shows every line at a second height too
    assert wider["visible"] is False, wider  # C1: expanded at three lines does not


def test_the_placeholder_never_shows_the_toggle_where_a_real_description_of_that_height_does(bundle):
    real = _run(bundle, SHORT, ["load|1", "resize|120|5"])
    assert [s["visible"] for s in real] == [False, True], real  # C1: a real description wrapped to five lines shows it

    placeholder = _run(bundle, "", ["load|1", "resize|120|5"])
    assert [s["text"] for s in placeholder] == [PLACEHOLDER, PLACEHOLDER]  # control: the placeholder is what is shown
    assert [s["visible"] for s in placeholder] == [False, False], placeholder  # C1: the same geometry never shows it for the placeholder


def test_activating_the_toggle_switches_between_four_lines_show_more_and_every_line_show_less(bundle):
    states = _run(bundle, LONG, ["load|6", "click", "click"])
    seen = [(s["visible"], s["shown"], s["label"], s["expanded"]) for s in states]

    assert seen[0] == (True, 4, "Show more", "false"), states[0]  # C2: collapsed at load
    assert seen[1] == (True, 6, "Show less", "true"), states[1]  # C2: the first activation shows every line
    assert seen[2] == (True, 4, "Show more", "false"), states[2]  # C2: the second returns to four lines
    assert [s["text"] for s in states] == [LONG] * 3  # C2: the clip is visual; the element keeps the full text
