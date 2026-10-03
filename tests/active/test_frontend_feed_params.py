"""`buildSimilarUrl` puts a feed mode on the Engine URL only when handed feed params: `buildSimilarUrl(q, resolveFeedParams(search))` carries the URL mode, else the legacy random flag, else the stored mode, else recommendations, with invalid values mapped to recommendations. Only this function pair is exercised; the home page module (`pages/videos/index.ts`) that calls it is not driven here.

`videos.ts` and `feed-params.ts` are bundled apart with esbuild and run in node with an in-memory `localStorage` on `globalThis` and `window`, so the harness is armed on `videos.ts` alone while `feed-params.ts` is missing, and a case needing it then reports esbuild's complaint in place of its modes. Each case starts from empty storage, may hold a raw value under `feedParams:v1`, and reports the `mode` entries (all of them) of the URL built for q = `{limit: "12"}`, whose path and limit are checked on every URL built. The modes iterated are the Engine's `FEED_MODES` tuple, read from `engine/server/api/handlers/similar.py`.

- The Engine's `FEED_MODES` name `trending` and not `hot`, and the feed-params bundle's `FEED_MODES` holds exactly the Engine's five modes, with none repeated.
- A legacy `hot` is read as `trending`: `?mode=hot` gives `["trending"]` with nothing stored and over a stored `recent`, a stored `{"mode": "hot"}` gives `["trending"]` to a bare search, and persisting what `?mode=hot` resolves to gives `["trending"]` to the next bare search. A bare JSON string `"hot"` stored still gives `["recommendations"]`.
- For each Engine mode: `?mode=<mode>` gives `[<mode>]` over a different stored mode, and also with `&random=1`.
- For each Engine mode: with that mode stored, no search, an empty `?mode=`, and a search of unrelated params each give `[<mode>]`.
- For each Engine mode: persisting what `?mode=<mode>` resolves to, then resolving a bare search, gives `[<mode>]`, onto empty storage and over a different stored mode.
- For each Engine mode but recommendations: with that mode stored a bare search gives `[<mode>]` and `?mode=<mode>` gives `[<mode>]`, while `?mode=bogus` gives `["recommendations"]` with that mode stored and with nothing stored.
- For each Engine mode but recommendations: the mode stored as a `{mode}` object gives `[<mode>]`, while the mode stored as a bare JSON string gives `["recommendations"]`.
- With `trending` stored a bare search gives `["trending"]`, while `?random=1` and `?mode=&random=1` give `["random"]`, as does `?random=1` with nothing stored.
- With `recent` stored a bare search gives `["recent"]`; with nothing stored, and with `null`, `[]`, unparsable JSON, an unknown mode, a null mode or `{}` stored, it gives `["recommendations"]`, without throwing.
- The same q with the params resolved from `?mode=trending` carries `["trending"]`, while `buildSimilarUrl(q)` with no feed params carries no `mode`, also with `trending` stored.

Only a stored NSFW setting of exactly "off" makes the up-next, feed and search requests carry nsfw=1. `videos.ts`, `search.ts` and `feed-params.ts` are bundled together and run in node with an in-memory `localStorage`, and each case loads a fresh module instance. A read builds `buildSimilarUrl` for an `?id=` up-next query with no feed params, and again for a query with the params `?mode=trending` resolves to, then makes one `fetchSearchResults({q: "music"})`.

- With `nsfwFilter:v1` holding "off", all three carry nsfw=1, on both the keyless (cached) and the keyed search branch.
- None carries nsfw when the value is "on" (keyed), missing, "OFF", "off ", '"off"', "{not json", "0" or "", or when getItem throws over a stored "off".
- With setItem throwing, setNsfwFilter(false) makes the next read carry nsfw=1, and setNsfwFilter(true) then makes it carry none. Over a stored "off", setNsfwFilter(true) makes the next read carry none.
- With working storage, setNsfwFilter(false) reads nsfw=1 on the same instance and on a fresh one. setNsfwFilter(true) then reads none on both.

The five-button pressed-state group and its reload are checked by hand in a browser.
"""
from __future__ import annotations

import ast
import atexit
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
SIMILAR_PY = ROOT / "engine" / "server" / "api" / "handlers" / "similar.py"
BASE = "http://client.test"
LIMIT = "12"
# The versioned key, next to localLikes:v1 and profileKey:v1.
STORAGE_KEY = "feedParams:v1"

# Each case starts from an empty storage, optionally holds `stored` raw under the key, optionally persists what `persist` (a search string) resolves to, then reports the Engine URL built for `search`; `bare` builds it with no feed params at all, and so needs only videos.ts.
RUNNER = """
const store = new Map();
const memory = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k) };
globalThis.localStorage = memory;
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { location: { origin: process.env.BASE }, localStorage: memory };
const videos = await import(process.env.VIDEOS);
const fp = process.env.FEED_PARAMS ? await import(process.env.FEED_PARAMS) : null;
const q = { limit: process.env.LIMIT };
const out = [];
for (const c of JSON.parse(process.env.CASES)) {
  store.clear();
  try {
    if (c.stored !== null) memory.setItem(process.env.STORAGE_KEY, c.stored);
    if (!c.bare && !fp) { out.push({ unresolved: process.env.FEED_PARAMS_ERROR }); continue; }
    if (c.persist !== null) fp.persistFeedParams(fp.resolveFeedParams(new URLSearchParams(c.persist)));
    const url = new URL(c.bare ? videos.buildSimilarUrl(q) : videos.buildSimilarUrl(q, fp.resolveFeedParams(new URLSearchParams(c.search))));
    out.push({ path: url.pathname, limit: url.searchParams.get("limit"), modes: url.searchParams.getAll("mode") });
  } catch (e) { out.push({ error: String(e && e.stack || e) }); }
}
const feedModes = fp ? Array.from(fp.FEED_MODES ?? []) : null;
process.stdout.write(JSON.stringify({ feedModes, results: out }) + "\\n", () => process.exit(0));
"""


def _tempdir() -> Path:
    out = Path(tempfile.mkdtemp(prefix="feed_params_"))
    atexit.register(shutil.rmtree, out, ignore_errors=True)
    return out


def _bundle(entry: str) -> tuple[Path | None, str]:
    """A bundle of `entry`, or None with esbuild's complaint."""
    out = _tempdir()
    (out / "entry.ts").write_text(entry)
    run = subprocess.run(
        [str(ESBUILD), str(out / "entry.ts"), "--bundle", "--format=esm", "--platform=node", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        return None, run.stderr[-2000:]
    return out / "bundle.mjs", ""


def _run(cases: list[dict]) -> dict:
    cases = [{"search": "", "stored": None, "persist": None, "bare": False, **c} for c in cases]
    proc = subprocess.run(
        ["node", str(RUNNER_FILE)], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "VIDEOS": str(VIDEOS), "FEED_PARAMS": str(FEED_PARAMS or ""), "FEED_PARAMS_ERROR": FEED_PARAMS_ERROR,
             "PATH": os.environ.get("PATH", ""), "LIMIT": LIMIT, "STORAGE_KEY": STORAGE_KEY, "CASES": json.dumps(cases)},
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout.splitlines()[-1])
    assert len(report["results"]) == len(cases), report
    for case, result in zip(cases, report["results"]):
        assert "error" not in result, (case, result["error"])
        if "unresolved" in result:
            continue
        # control: q reached the URL untouched, so a missing mode below is the feed params', not a broken build of the query
        assert (result["path"], result["limit"]) == ("/recommendations", LIMIT), (case, result)
    return report


def _modes(cases: list[dict]) -> list:
    """Each case's mode list, or why feed-params.ts could not be asked."""
    return [r["modes"] if "modes" in r else f"feed-params.ts did not bundle: {r['unresolved']}" for r in _run(cases)["results"]]


def _engine_feed_modes() -> list[str]:
    """The Engine's FEED_MODES tuple, read from its source rather than imported (the import needs the Engine's numpy and faiss)."""
    for node in ast.parse(SIMILAR_PY.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FEED_MODES" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise AssertionError(f"no FEED_MODES assignment in {SIMILAR_PY}")


def _stored(mode: str) -> str:
    return json.dumps({"mode": mode})


ENGINE_FEED_MODES = _engine_feed_modes()
VIDEOS, VIDEOS_ERROR = _bundle(f'export {{ buildSimilarUrl }} from "{FRONTEND}/src/data/videos.ts";\n')
FEED_PARAMS, FEED_PARAMS_ERROR = _bundle(f'export {{ FEED_MODES, resolveFeedParams, persistFeedParams }} from "{FRONTEND}/src/data/feed-params.ts";\n')
RUNNER_FILE = _tempdir() / "runner.mjs"
RUNNER_FILE.write_text(RUNNER)


# The default is left out where recommendations is the expected reading, since there a resolve ignoring its input would read the same.
NON_DEFAULT_MODES = [m for m in ENGINE_FEED_MODES if m != "recommendations"]


def _other(mode: str) -> str:
    """An Engine mode other than `mode`, so a stored value that wins over the URL shows."""
    return next(m for m in ENGINE_FEED_MODES if m != mode)


def test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot():
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    assert len(ENGINE_FEED_MODES) == 5, ENGINE_FEED_MODES  # control: the Engine's five modes (recommendations, trending, recent, random, popular)
    # The Engine's FEED_MODES is read from similar.py by AST: the client bundle cannot reach the Engine, so its tuple's value is the only observable at this seam. With trending and hot swapped back, the equality below still holds.
    assert "trending" in ENGINE_FEED_MODES and "hot" not in ENGINE_FEED_MODES, ENGINE_FEED_MODES
    client = _run([])["feedModes"]
    # A client list short of a mode maps that mode to recommendations; one with an extra mode sends it to an Engine that answers 400.
    assert client is not None and sorted(client) == sorted(ENGINE_FEED_MODES) and len(set(client)) == len(client), (client, ENGINE_FEED_MODES, FEED_PARAMS_ERROR)


def test_a_legacy_hot_from_the_url_or_a_stored_mode_object_requests_trending_and_a_bare_hot_string_does_not():
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    got = _modes([
        {"search": "?mode=hot"},
        {"search": "?mode=hot", "stored": _stored("recent")},
        {"search": "", "stored": _stored("hot")},
        {"search": "", "persist": "?mode=hot"},
        {"search": "", "stored": json.dumps("hot")},
    ])
    # The previous client gives ["hot"], which the Engine answers 400; a rename with no alias gives ["recommendations"].
    assert got[0] == ["trending"], got[0]
    # An alias that falls through to storage gives ["recent"].
    assert got[1] == ["trending"], got[1]
    # An alias applied only to the URL gives ["recommendations"] for the stored object.
    assert got[2] == ["trending"], got[2]
    # What a ?mode=hot visit persists is read back as a mode the Engine accepts, not ["hot"].
    assert got[3] == ["trending"], got[3]
    # Storage holds an object, so a bare JSON string "hot" is not a stored choice; an alias applied before the object check gives ["trending"].
    assert got[4] == ["recommendations"], got[4]


@pytest.mark.parametrize("mode", ENGINE_FEED_MODES)
def test_the_url_mode_beats_the_stored_mode_and_the_legacy_random_flag(mode):
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    other = _other(mode)
    got = _modes([
        {"search": f"?mode={mode}", "stored": _stored(other)},
        {"search": f"?mode={mode}&random=1", "stored": _stored(other)},
    ])
    # buildSimilarUrl ignoring its second argument gives []; a stored-first resolve gives [other]; a legacy-first one gives ["random"].
    assert got[0] == [mode], (mode, other, got[0])
    assert got[1] == [mode], (mode, got[1])


@pytest.mark.parametrize("mode", ENGINE_FEED_MODES)
def test_with_no_url_mode_the_stored_mode_is_sent_and_an_empty_mode_falls_through_to_it(mode):
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    got = _modes([
        {"search": "", "stored": _stored(mode)},
        {"search": "?mode=", "stored": _stored(mode)},
        {"search": "?host=peer.example&limit=3", "stored": _stored(mode)},
    ])
    # A resolve that never reads storage gives ["recommendations"]; one treating an empty ?mode= as invalid gives it too.
    assert got[0] == [mode], (mode, got[0])
    assert got[1] == [mode], (mode, got[1])
    assert got[2] == [mode], (mode, got[2])


@pytest.mark.parametrize("mode", ENGINE_FEED_MODES)
def test_a_persisted_mode_is_what_a_bare_resolve_sends_next(mode):
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    got = _modes([
        {"search": "", "persist": f"?mode={mode}"},
        {"search": "", "stored": _stored(_other(mode)), "persist": f"?mode={mode}"},
    ])
    # A persist writing nowhere, or to a key the resolve does not read, gives ["recommendations"]; one that does not overwrite gives the older choice.
    assert got[0] == [mode], (mode, got[0])
    assert got[1] == [mode], (mode, got[1])


@pytest.mark.parametrize("mode", NON_DEFAULT_MODES)
def test_an_invalid_url_mode_gives_recommendations_even_over_a_stored_mode(mode):
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    got = _modes([
        {"search": "", "stored": _stored(mode)},
        {"search": f"?mode={mode}"},
        {"search": "?mode=bogus", "stored": _stored(mode)},
        {"search": "?mode=bogus"},
    ])
    # The stored and the URL value are both read, so recommendations below is the invalid mapping, not a resolve that always answers the default.
    assert got[0] == [mode], (mode, got[0])
    assert got[1] == [mode], (mode, got[1])
    # A resolve passing the raw value through gives ["bogus"], which the Engine answers 400; one falling through to storage gives [mode].
    assert got[2] == ["recommendations"], (mode, got[2])
    assert got[3] == ["recommendations"], got[3]


@pytest.mark.parametrize("mode", NON_DEFAULT_MODES)
def test_a_stored_bare_string_mode_gives_recommendations(mode):
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    got = _modes([{"search": "", "stored": _stored(mode)}, {"search": "", "stored": json.dumps(mode)}])
    # The same mode stored as an object is read, so recommendations below is the bare string rejected, not storage never read.
    assert got[0] == [mode], (mode, got[0])
    # Storage holds an object, so a bare JSON string mode is not a stored choice; a resolve accepting it gives [mode].
    assert got[1] == ["recommendations"], (mode, got[1])


def test_the_legacy_random_flag_gives_random_over_a_stored_mode():
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    stored = _stored("trending")
    got = _modes([
        {"search": "", "stored": stored},
        {"search": "?random=1", "stored": stored},
        {"search": "?mode=&random=1", "stored": stored},
        {"search": "?random=1"},
    ])
    # The stored value is read, so the cases below are the flag winning over it.
    assert got[0] == ["trending"], got[0]
    # A resolve ignoring the flag gives ["trending"] or ["recommendations"].
    assert got[1] == ["random"], got[1]
    assert got[2] == ["random"], got[2]
    assert got[3] == ["random"], got[3]


def test_unusable_stored_values_give_recommendations():
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    unusable = ["null", "[]", "{not json", _stored("bogus"), json.dumps({"mode": None}), "{}"]
    got = _modes([{"search": "", "stored": _stored("recent")}, {"search": ""}] + [{"search": "", "stored": raw} for raw in unusable])
    # A usable stored value is read, so recommendations below is the fallback, not storage never read.
    assert got[0] == ["recent"], got[0]
    assert got[1] == ["recommendations"], got[1]  # nothing stored
    # Bad JSON that throws out of resolve fails in _run with its error; an unknown mode passed through gives ["bogus"].
    assert got[2:] == [["recommendations"]] * len(unusable), list(zip(unusable, got[2:]))


def test_build_similar_url_with_no_feed_params_carries_no_mode():
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    got = _modes([
        {"search": "?mode=trending", "stored": _stored("trending")},
        {"bare": True},
        {"bare": True, "stored": _stored("trending")},
    ])
    # With params the query carries the mode, which arms the absences below.
    assert got[0] == ["trending"], got[0]
    # A buildSimilarUrl that resolves the mode itself, or defaults it, carries one without being given params.
    assert got[1] == [], got[1]
    assert got[2] == [], got[2]


# The NSFW setting: its key and its one "off" value, kept apart from feedParams:v1.
NSFW_KEY = "nsfwFilter:v1"
PROFILE_KEY = "profileKey:v1"
SEARCH_PATH = "/api/v1/search/videos"
NSFW_OFF = {"bare": ["1"], "feed": ["1"], "search": ["1"]}
NSFW_ON = {"bare": [], "feed": [], "search": []}
# Stored values that are not exactly "off": near misses a trimmed, case-folded or JSON-parsing reader would take as off, and corrupt ones.
NSFW_ON_READINGS = {"missing": None, "on": "on", "upper": "OFF", "padded": "off ", "json-string": '"off"', "corrupt-json": "{not json", "zero": "0", "empty": ""}

# Each case gets a fresh storage and a fresh module instance (a new ?load= URL), so no in-memory setting carries over; `reload` loads another instance over the same storage, as a new page view would. A read builds the ?id= up-next URL (no feed params), the ?mode=trending feed URL (with feed params) and one search request.
NSFW_RUNNER = """
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
      const feed = new URL(m.buildSimilarUrl({ limit: "12" }, m.feedParams.resolveFeedParams(new URLSearchParams("?mode=trending"))));
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

# One bundle, so videos.ts, search.ts and the runner share one feed-params instance; the namespace export keeps a missing helper an undefined member rather than a build error.
NSFW_BUNDLE, NSFW_BUNDLE_ERROR = _bundle(
    f'export {{ buildSimilarUrl }} from "{FRONTEND}/src/data/videos.ts";\n'
    f'export {{ fetchSearchResults }} from "{FRONTEND}/src/data/search.ts";\n'
    f'export * as feedParams from "{FRONTEND}/src/data/feed-params.ts";\n'
)
NSFW_RUNNER_FILE = _tempdir() / "nsfw_runner.mjs"
NSFW_RUNNER_FILE.write_text(NSFW_RUNNER)


def _nsfw_case(stored: str | None = None, *, steps: list[str] = ("read",), profile_key: bool = False, get_throws: bool = False, set_throws: bool = False) -> dict:
    return {"stored": stored, "profileKey": profile_key, "getThrows": get_throws, "setThrows": set_throws, "steps": list(steps)}


def _nsfw_run(cases: dict[str, dict]) -> dict[str, list[dict]]:
    """Each case's reads, as the nsfw values of its up-next, feed and search URLs plus whether search went keyed."""
    assert NSFW_BUNDLE is not None, NSFW_BUNDLE_ERROR  # control: videos.ts, search.ts and feed-params.ts bundle together
    proc = subprocess.run(
        ["node", str(NSFW_RUNNER_FILE)], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(NSFW_BUNDLE), "PATH": os.environ.get("PATH", ""), "NSFW_KEY": NSFW_KEY, "PROFILE_KEY": PROFILE_KEY,
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
            assert (read["feed"]["path"], read["feed"]["mode"]) == ("/recommendations", ["trending"]), (label, read["feed"])
            assert [(s["path"], s["q"]) for s in read["search"]] == [(SEARCH_PATH, "music")], (label, read["search"])
        got[label] = [{"bare": r["bare"]["nsfw"], "feed": r["feed"]["nsfw"], "search": r["search"][0]["nsfw"], "keyed": r["search"][0]["keyed"]} for r in result["reads"]]
    return got


def _nsfw(read: dict) -> dict:
    return {k: read[k] for k in ("bare", "feed", "search")}


def test_only_a_stored_off_puts_nsfw_1_on_up_next_feed_and_search_requests():
    cases = {
        "off": _nsfw_case("off"),
        "off-keyed": _nsfw_case("off", profile_key=True),
        "on-keyed": _nsfw_case("on", profile_key=True),
        # The stored "off" is there to be read, so only a reader that catches the throw and falls back to on passes.
        "unreadable": _nsfw_case("off", get_throws=True),
        **{label: _nsfw_case(value) for label, value in NSFW_ON_READINGS.items()},
    }
    got = _nsfw_run(cases)

    # A reader ignoring storage, or a buildSimilarUrl adding nsfw only with feed params, or a search left unchanged, leaves one of these [].
    assert _nsfw(got["off"][0]) == NSFW_OFF, got["off"]
    assert got["off"][0]["keyed"] is False, got["off"]  # control: the keyless, cached search branch
    # The keyed search branch fetches directly, so an nsfw set only on the cached branch misses it.
    assert got["off-keyed"][0]["keyed"] is True, got["off-keyed"]  # control: the keyed branch was taken
    assert _nsfw(got["off-keyed"][0]) == NSFW_OFF, got["off-keyed"]
    assert got["on-keyed"][0]["keyed"] is True, got["on-keyed"]
    assert _nsfw(got["on-keyed"][0]) == NSFW_ON, got["on-keyed"]
    # A reader defaulting to off, one reading anything but "on" as off, or one trimming, case-folding or JSON-parsing the value, puts nsfw=1 on at least one of these; an uncaught getItem throw fails in _nsfw_run.
    readings = {label: _nsfw(got[label][0]) for label in ["unreadable", *NSFW_ON_READINGS]}
    assert readings == {label: NSFW_ON for label in readings}, readings


def test_set_nsfw_filter_holds_on_the_page_when_set_item_throws():
    got = _nsfw_run({
        "empty": _nsfw_case(None, set_throws=True, steps=["read", "set:false", "read", "set:true", "read"]),
        "stored-off": _nsfw_case("off", set_throws=True, steps=["read", "set:true", "read"]),
    })

    # control: the filter reads on before the first set, so nsfw=1 after it is the set's doing
    assert _nsfw(got["empty"][0]) == NSFW_ON, got["empty"]
    # A setter that only writes storage leaves the throwing write with no effect, so the URL stays filtered.
    assert _nsfw(got["empty"][1]) == NSFW_OFF, got["empty"]
    assert _nsfw(got["empty"][2]) == NSFW_ON, got["empty"]
    # control: the stored "off" is read before the set
    assert _nsfw(got["stored-off"][0]) == NSFW_OFF, got["stored-off"]
    # A reader checking storage before the in-memory choice goes on reading the stored "off".
    assert _nsfw(got["stored-off"][1]) == NSFW_ON, got["stored-off"]


def test_set_nsfw_filter_is_read_back_by_the_next_page_view():
    got = _nsfw_run({"persist": _nsfw_case(None, steps=["set:false", "read", "reload", "read", "set:true", "read", "reload", "read"])})
    reads = [_nsfw(read) for read in got["persist"]]

    # A fresh module instance holds no in-memory choice, so the reads after each reload come from what the setter stored; a setter that keeps the choice only in memory reads on after the first reload.
    assert reads == [NSFW_OFF, NSFW_OFF, NSFW_ON, NSFW_ON], reads
