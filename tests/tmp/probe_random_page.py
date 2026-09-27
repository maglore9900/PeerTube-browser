"""Probe: run the real Home page script in node with a minimal DOM, in random and home modes,
against the live Client, and report what ends up in the cards grid."""
import json
import os
import subprocess
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://127.0.0.1:7072"

RUNNER = r"""
const log = (...a) => process.stdout.write(a.map(String).join(" ") + "\n");
process.on("unhandledRejection", (e) => log("UNHANDLED", e && e.stack || e));
process.on("uncaughtException", (e) => log("UNCAUGHT", e && e.stack || e));
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
const elements = new Map();
function el(id) {
  if (!elements.has(id)) {
    const e = { id, innerHTML: "", textContent: "", hidden: false, dataset: {}, style: {},
      _attrs: {}, children: [],
      addEventListener() {}, removeAttribute(n) { delete this._attrs[n]; }, setAttribute(n, v) { this._attrs[n] = v; },
      hasAttribute(n) { return n in this._attrs; }, focus() {}, append() {}, replaceChildren(...c) { this.innerHTML = "[children]"; },
      querySelectorAll(sel) { return sel === ".video-card" ? Array.from({ length: (this.innerHTML.match(/<article/g) || []).length }) : []; },
      querySelector() { return null; },
      insertAdjacentHTML(_p, html) { this.innerHTML += html; },
      getBoundingClientRect() { return { top: 99999 }; } };
    elements.set(id, e);
  }
  return elements.get(id);
}
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
if (process.env.KEY) localStorage.setItem("profileKey:v1", process.env.KEY);
globalThis.document = { getElementById: (id) => el(id), title: "", body: { dataset: {} },
  documentElement: { scrollHeight: 100000 }, createElement: () => el("tmp" + Math.random()) };
globalThis.window = { location: { origin: process.env.BASE, search: process.env.SEARCH, pathname: "/" },
  localStorage, addEventListener() {}, innerHeight: 800, scrollY: 0, confirm: () => false };
globalThis.IntersectionObserver = class { constructor() {} observe() {} disconnect() {} };
globalThis.CSS = { escape: (s) => s };
await import(process.env.BUNDLE);
await new Promise((r) => setTimeout(r, 4000));
const cards = el("video-cards").innerHTML;
log("CARDS", (cards.match(/<article/g) || []).length, "articles; head:", cards.slice(0, 160).replace(/\s+/g, " "));
process.exit(0);
"""


def _bundle(tmp_path: Path) -> Path:
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src/pages/videos/index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={tmp_path / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True)
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER)
    return runner


def _call(method, path, body, key=None):
    from urllib.request import Request, urlopen
    headers = {"content-type": "application/json", **({"X-Profile-Key": key} if key else {})}
    with urlopen(Request(BASE + path, data=json.dumps(body).encode(), method=method, headers=headers), timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def test_probe(tmp_path):
    runner = _bundle(tmp_path)
    key = _call("POST", "/api/profile", {})["key"]
    row = _call("POST", "/recommendations?random=1", {})["rows"][0]
    _call("POST", "/api/profile/blocks", {"kind": "channel", "uuid": row["video_uuid"], "host": row["instance_domain"]}, key)
    try:
        _run(runner, tmp_path, key)
    finally:
        _call("POST", "/api/profile/delete", {}, key)


def _run(runner, tmp_path, key):
    for search in ("?mode=random", ""):
        proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=60,
                              env={"PATH": os.environ["PATH"], "BASE": BASE, "BUNDLE": str(tmp_path / "bundle.mjs"),
                                   "SEARCH": search, "KEY": key})
        print("SEARCH", repr(search), "rc", proc.returncode)
        print(proc.stdout[-2000:])
        print(proc.stderr[-1500:])
