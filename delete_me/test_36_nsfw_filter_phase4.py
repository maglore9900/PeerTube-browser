"""Only a stored NSFW setting of exactly "off" makes the up-next, feed and search requests carry nsfw=1, and the home Profile modal's checkbox, in each profile state, reloads the feed under its new value and leaves the page fetched under that value shown.

Data modules: `videos.ts`, `search.ts` and `feed-params.ts` are bundled together and run in node with an in-memory `localStorage`, and each case loads a fresh module instance. A read builds `buildSimilarUrl` for an `?id=` up-next query with no feed params, and again for a query with the params `?mode=hot` resolves to, then makes one `fetchSearchResults({q: "music"})`.
- With `nsfwFilter:v1` holding "off", all three carry nsfw=1, on both the keyless (cached) and the keyed search branch.
- None carries nsfw when the value is "on" (keyed), missing, "OFF", "off ", '"off"', "{not json", "0" or "", or when getItem throws over a stored "off".
- With setItem throwing, setNsfwFilter(false) makes the next read carry nsfw=1, and setNsfwFilter(true) then makes it carry none. Over a stored "off", setNsfwFilter(true) makes the next read carry none.
- With working storage, setNsfwFilter(false) reads nsfw=1 on the same instance and on a fresh one. setNsfwFilter(true) then reads none on both.

Home page: `pages/videos/index.ts` is bundled and run in node against recording elements and a stub fetch. It runs for a keyless visitor, a visitor holding a key, and one who has just clicked "Create profile" (the issued-key view).
- The first feed request is to /recommendations with mode recommendations and no nsfw, and its response is held.
- The Profile modal holds exactly one checkbox, and it is checked.
- Unchecking the box (click, input, change) sends exactly one more feed request, with mode recommendations and nsfw=1, which is answered at once. The held first page is then released and read by the page, and the feed shows the second page's rows.
- Checking it again sends one more feed request, with no nsfw, and the feed shows that third page's rows.

The feed is read as the `data-video-key`s in `#video-cards`. The checkbox's label text, its place in the modal and its styling are not asserted. The video and search pages are not driven, so whether they build their requests through `buildSimilarUrl` and `fetchSearchResults` is not asserted.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
# The plan's key and its one "off" value, kept apart from feedParams:v1.
NSFW_KEY = "nsfwFilter:v1"
PROFILE_KEY = "profileKey:v1"
SEARCH_PATH = "/api/v1/search/videos"
OFF = {"bare": ["1"], "feed": ["1"], "search": ["1"]}
ON = {"bare": [], "feed": [], "search": []}
# Stored values that are not exactly "off": near misses a trimmed, case-folded or JSON-parsing reader would take as off, and corrupt ones.
ON_READINGS = {"missing": None, "on": "on", "upper": "OFF", "padded": "off ", "json-string": '"off"', "corrupt-json": "{not json", "zero": "0", "empty": ""}

# Each case gets a fresh storage and a fresh module instance (a new ?load= URL), so no in-memory setting carries over; `reload` loads another instance over the same storage, as a new page view would. A read builds the ?id= up-next URL (no feed params), the ?mode=hot feed URL (with feed params) and one search request.
DATA_RUNNER = """
import { pathToFileURL } from "node:url";
const bundleUrl = pathToFileURL(process.env.BUNDLE).href;
const store = new Map();
const flags = { getThrows: false, setThrows: false };
const memory = { getItem: (k) => { if (flags.getThrows) throw new Error("SecurityError"); return store.has(k) ? store.get(k) : null; },
  setItem: (k, v) => { if (flags.setThrows) throw new Error("QuotaExceededError"); store.set(k, String(v)); }, removeItem: (k) => store.delete(k) };
globalThis.localStorage = memory;
// Search caches keyless pages by URL in sessionStorage; a store that keeps nothing makes every read reach fetch.
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { location: { origin: process.env.BASE }, localStorage: memory, sessionStorage: globalThis.sessionStorage };
const fetched = [];
globalThis.fetch = async (input, init) => { fetched.push({ url: String(input?.url ?? input), key: (init?.headers ?? {})["x-profile-key"] ?? null });
  return new Response(JSON.stringify({ rows: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } }); };
let loads = 0;
const load = async () => { loads += 1; return import(`${bundleUrl}?load=${loads}`); };
const out = [];
for (const c of JSON.parse(process.env.CASES)) {
  store.clear(); flags.getThrows = false; flags.setThrows = false;
  if (c.stored !== null) store.set(process.env.NSFW_KEY, c.stored);
  if (c.profileKey) store.set(process.env.PROFILE_KEY, "K".repeat(43));
  flags.getThrows = c.getThrows; flags.setThrows = c.setThrows;
  const reads = [];
  try {
    let m = await load();
    for (const step of c.steps) {
      if (step === "reload") { m = await load(); continue; }
      if (step.startsWith("set:")) { m.feedParams.setNsfwFilter(step === "set:true"); continue; }
      fetched.length = 0;
      const bare = new URL(m.buildSimilarUrl({ id: "v1", host: "peer.example", limit: "12" }));
      const feed = new URL(m.buildSimilarUrl({ limit: "12" }, m.feedParams.resolveFeedParams(new URLSearchParams("?mode=hot"))));
      await m.fetchSearchResults({ q: "music" });
      reads.push({ bare: { path: bare.pathname, id: bare.searchParams.get("id"), mode: bare.searchParams.getAll("mode"), nsfw: bare.searchParams.getAll("nsfw") },
        feed: { path: feed.pathname, mode: feed.searchParams.getAll("mode"), nsfw: feed.searchParams.getAll("nsfw") },
        search: fetched.map((f) => { const url = new URL(f.url); return { path: url.pathname, q: url.searchParams.get("q"), keyed: f.key !== null, nsfw: url.searchParams.getAll("nsfw") }; }) });
    }
    out.push({ reads });
  } catch (e) { out.push({ reads, error: String(e && e.stack || e) }); }
}
process.stdout.write(JSON.stringify(out) + "\\n", () => process.exit(0));
"""

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


def _esbuild(args: list[str], out: Path) -> None:
    run = subprocess.run(
        [str(ESBUILD), *args, "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr[-2000:]


@pytest.fixture(scope="module")
def data_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("nsfw_data")
    # One bundle, so videos.ts, search.ts and the test share one feed-params instance; the namespace export keeps a missing helper an undefined member rather than a build error.
    (out / "entry.ts").write_text(
        f'export {{ buildSimilarUrl }} from "{FRONTEND}/src/data/videos.ts";\n'
        f'export {{ fetchSearchResults }} from "{FRONTEND}/src/data/search.ts";\n'
        f'export * as feedParams from "{FRONTEND}/src/data/feed-params.ts";\n'
    )
    _esbuild([str(out / "entry.ts")], out / "bundle.mjs")
    (out / "runner.mjs").write_text(DATA_RUNNER)
    return out


@pytest.fixture(scope="module")
def home_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("nsfw_home")
    _esbuild([str(FRONTEND / "src" / "pages" / "videos" / "index.ts")], out / "bundle.mjs")
    (out / "runner.mjs").write_text(HOME_RUNNER)
    return out


def _case(stored: str | None = None, *, steps: list[str] = ("read",), profile_key: bool = False, get_throws: bool = False, set_throws: bool = False) -> dict:
    return {"stored": stored, "profileKey": profile_key, "getThrows": get_throws, "setThrows": set_throws, "steps": list(steps)}


def _run(bundle: Path, cases: dict[str, dict]) -> dict[str, list[dict]]:
    """Each case's reads, as the nsfw values of its up-next, feed and search URLs plus whether search went keyed."""
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "NSFW_KEY": NSFW_KEY, "PROFILE_KEY": PROFILE_KEY,
             "CASES": json.dumps(list(cases.values()))},
    )
    assert proc.returncode == 0, proc.stderr
    results = json.loads(proc.stdout.splitlines()[-1])
    assert len(results) == len(cases), results
    got = {}
    for label, result in zip(cases, results):
        assert "error" not in result, (label, result["error"])
        assert len(result["reads"]) == cases[label]["steps"].count("read"), (label, result)
        for read in result["reads"]:
            # control: each URL is the one meant, so a missing nsfw below is the setting's, not a broken build of the request; the up-next URL is built with no feed params and the feed URL with them
            assert (read["bare"]["path"], read["bare"]["id"], read["bare"]["mode"]) == ("/recommendations", "v1", []), (label, read["bare"])
            assert (read["feed"]["path"], read["feed"]["mode"]) == ("/recommendations", ["hot"]), (label, read["feed"])
            assert [(s["path"], s["q"]) for s in read["search"]] == [(SEARCH_PATH, "music")], (label, read["search"])
        got[label] = [{"bare": r["bare"]["nsfw"], "feed": r["feed"]["nsfw"], "search": r["search"][0]["nsfw"], "keyed": r["search"][0]["keyed"]} for r in result["reads"]]
    return got


def _nsfw(read: dict) -> dict:
    return {k: read[k] for k in ("bare", "feed", "search")}


def test_only_a_stored_off_puts_nsfw_1_on_up_next_feed_and_search_requests(data_bundle):
    cases = {
        "off": _case("off"),
        "off-keyed": _case("off", profile_key=True),
        "on-keyed": _case("on", profile_key=True),
        # The stored "off" is there to be read, so only a reader that catches the throw and falls back to on passes.
        "unreadable": _case("off", get_throws=True),
        **{label: _case(value) for label, value in ON_READINGS.items()},
    }
    got = _run(data_bundle, cases)

    # A reader ignoring storage, or a buildSimilarUrl adding nsfw only with feed params, or a search left unchanged, leaves one of these [].
    assert _nsfw(got["off"][0]) == OFF, got["off"]  # C1
    assert got["off"][0]["keyed"] is False, got["off"]  # control: the keyless, cached search branch
    # The keyed search branch fetches directly, so an nsfw set only on the cached branch misses it.
    assert got["off-keyed"][0]["keyed"] is True, got["off-keyed"]  # control: the keyed branch was taken
    assert _nsfw(got["off-keyed"][0]) == OFF, got["off-keyed"]  # C1
    assert got["on-keyed"][0]["keyed"] is True, got["on-keyed"]
    assert _nsfw(got["on-keyed"][0]) == ON, got["on-keyed"]  # C1
    # A reader defaulting to off, one reading anything but "on" as off, or one trimming, case-folding or JSON-parsing the value, puts nsfw=1 on at least one of these; an uncaught getItem throw fails in _run.
    readings = {label: _nsfw(got[label][0]) for label in ["unreadable", *ON_READINGS]}
    assert readings == {label: ON for label in readings}, readings  # C1


def test_set_nsfw_filter_holds_on_the_page_when_set_item_throws(data_bundle):
    got = _run(data_bundle, {
        "empty": _case(None, set_throws=True, steps=["read", "set:false", "read", "set:true", "read"]),
        "stored-off": _case("off", set_throws=True, steps=["read", "set:true", "read"]),
    })

    # control: the filter reads on before the first set, so nsfw=1 after it is the set's doing
    assert _nsfw(got["empty"][0]) == ON, got["empty"]
    # A setter that only writes storage leaves the throwing write with no effect, so the URL stays filtered.
    assert _nsfw(got["empty"][1]) == OFF, got["empty"]  # C1
    assert _nsfw(got["empty"][2]) == ON, got["empty"]  # C1
    # control: the stored "off" is read before the set
    assert _nsfw(got["stored-off"][0]) == OFF, got["stored-off"]
    # A reader checking storage before the in-memory choice goes on reading the stored "off".
    assert _nsfw(got["stored-off"][1]) == ON, got["stored-off"]  # C1


def test_set_nsfw_filter_is_read_back_by_the_next_page_view(data_bundle):
    got = _run(data_bundle, {"persist": _case(None, steps=["set:false", "read", "reload", "read", "set:true", "read", "reload", "read"])})
    reads = [_nsfw(read) for read in got["persist"]]

    # A fresh module instance holds no in-memory choice, so the reads after each reload come from what the setter stored; a setter that keeps the choice only in memory reads on after the first reload.
    assert reads == [OFF, OFF, ON, ON], reads  # C1


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
    assert page["checkboxes"] == [{"checked": True}], (page["checkboxes"], page["rejections"])  # C2
    # Unchecking reloads the same feed once, now opted in; a handler that saves without reloading adds no request, and a URL built from a setting captured at page load carries no nsfw.
    assert page["afterOff"]["feed"] == [{"mode": HOME_FEED, "nsfw": []}, {"mode": HOME_FEED, "nsfw": ["1"]}], (page["afterOff"], page["rejections"])  # C2
    # control: the held first page reached the page after the toggle's page had rendered, so the stale result was there to be dropped
    assert page["afterRelease"]["firstBodyRead"] is True, page["afterRelease"]
    # A load that renders whichever response arrives last shows the first page's keys here.
    assert page["afterRelease"]["cards"] == _keys(TURNED_OFF), (page["afterOff"]["cards"], page["afterRelease"], page["rejections"])  # C2
    # Checking it again reloads filtered; a handler that always turns the filter off sends nsfw=1 again.
    assert page["afterOn"]["feed"][2:] == [{"mode": HOME_FEED, "nsfw": []}], page["afterOn"]  # C2
    assert page["afterOn"]["cards"] == _keys(TURNED_ON), (page["afterOn"], page["rejections"])  # C2
