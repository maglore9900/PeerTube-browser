"""The frontend's feed pager over up-next similars, run in node against the real Client and Engine at the video page's 48-row batch: its batches never repeat a row, and it stops asking once a batch adds nothing.

- For the linux seed, the pager's first batch is an up-next page (`seed.mode == "upnext"`), its second batch holds rows and none of the first batch's, and no later batch repeats a row of an earlier one. Each batch is a random draw (build 09), so no two pages are compared for equality.
- The pager is driven for MAX_BATCHES calls and reaches an empty batch before the last: the Engine takes a seed's top 300 rows before it drops excluded ones, so at 48 a batch the pool runs out in about 7. No call after the empty batch makes a request, counted on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).
- Every batch before the last non-empty one holds exactly 48 rows, and that one holds 1 to 48. The similars default is also 48 (a run with no `limit` came back 48 x 6, 12), so a second run of the same seed at limit 20 for 2 batches must come back 20 x 2: the batch size follows the `limit` sent, not the default.
- The pager assertions above characterise an unchanged `data/videos.ts` and are green before this phase lands. What this test checks of the phase is its output. The durable `tests/active/test_frontend_upnext_pager.py` exists, and its test passes when its `_run` hands it the batches of a pager that holds the contract (48 x 6, 12, then empty, calls 1..8 then flat) but fails with an AssertionError on the batches of a pager that repeats a row of an earlier batch, never runs dry, keeps asking after the empty batch, resolves to a mode other than up-next, returns an empty second batch, or crashes partway. The batches are canned, so the durable file's live run is not repeated here; the live run is the one above. A test group named `test_frontend_upnext_pager.py` is discovered in tests/active, and the files validate_tests.py fingerprints it over (`claimed`, read from config.json's test_groups) include `data/videos.ts`, the Client's `server.py`, and the Engine's `similarity_candidates.py` and `handlers/similar.py`, so it is reselected when any of them changes. The modules `data/videos.ts` imports (`cache`, `local-likes`, `api-base`, `profile`) are not in the plan's mapping and are not checked.

Replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones, as `test_frontend_video_page.py` does.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

from conftest import engine, engine_client  # noqa: E402,F401

FRONTEND = ROOT / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
PAGE = "48"
MAX_BATCHES = 10
HARNESS = ROOT / ".un" / "skills" / "devsecops" / "scripts" / "validate_tests.py"
DURABLE = ACTIVE_DIR / "test_frontend_upnext_pager.py"
SUBJECTS = ["client/frontend/src/data/videos.ts", "client/backend/server.py", "engine/server/data/similarity_candidates.py", "engine/server/api/handlers/similar.py"]

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage,
  sessionStorage: globalThis.sessionStorage };
const m = await import(process.env.BUNDLE);
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\\n");
const keys = (rows) => (rows ?? []).map((r) => [r.video_id, r.instance_domain]);
const query = { id: process.env.SEED_UUID, host: process.env.SEED_HOST, limit: process.env.PAGE,
  apiBase: process.env.BASE };
let calls = 0;
try {
  const pager = m.createFeedPager((exclude) => { calls += 1; return m.fetchSimilarVideosPayload(query, exclude); });
  for (let i = 0; i < Number(process.env.MAX_BATCHES); i += 1) {
    const payload = await pager.next();
    say({ rows: keys(payload.rows), mode: payload.seed?.mode ?? null, calls });
  }
} catch (e) { say({ error: String(e), calls }); }
process.exit(0);
"""


def _run(tmp_path: Path, base: str, seed: dict, page: str = PAGE, max_batches: int = MAX_BATCHES) -> list[dict]:
    entry = tmp_path / "entry.ts"
    entry.write_text(f'export {{ createFeedPager, fetchSimilarVideosPayload }} from "{FRONTEND}/src/data/videos.ts";\n')
    subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node",
         f"--outfile={tmp_path / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER)
    proc = subprocess.run(
        ["node", str(runner)], capture_output=True, text=True, timeout=300,
        env={"BASE": base, "BUNDLE": str(tmp_path / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "SEED_UUID": seed["video_uuid"], "SEED_HOST": seed["instance_domain"],
             "PAGE": page, "MAX_BATCHES": str(max_batches)},
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def _seed(client) -> dict:
    # A seed whose up-next pool is the full 300: at 48 a batch it came back 48 x 6, then 12, then empty at batch 8.
    status, body = client.request("GET", "/api/v1/search/videos?q=linux&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canned(sizes, calls, mode: str = "upnext") -> list[dict]:
    ids = iter(range(10_000))
    return [{"rows": [[f"v{next(ids)}", "videos.example"] for _ in range(n)], "mode": mode, "calls": c} for n, c in zip(sizes, calls)]


def _fails(durable, batches: list[dict], tmp_path: Path) -> bool:
    # the durable file's own helpers are replaced, so its assertions read these batches and not a live run
    durable._seed = lambda client: {}
    durable._run = lambda *args: batches
    try:
        for name, test in vars(durable).items():
            if name.startswith("test_"):
                test(engine_client=types.SimpleNamespace(base=""), tmp_path=tmp_path)
    except AssertionError:
        return True
    return False


def test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(
        engine_client, tmp_path):
    seed = _seed(engine_client)
    batches = _run(tmp_path, engine_client.base, seed)
    assert all("error" not in b for b in batches), batches
    assert len(batches) == MAX_BATCHES, batches
    assert batches[0]["mode"] == "upnext", batches[0]  # control: the seed resolves to up-next

    first, second = (set(map(tuple, b["rows"])) for b in batches[:2])
    assert first, "the first batch is empty"
    assert second, "the second batch is empty"  # C1
    assert not first & second, first & second  # C1
    seen: set[tuple] = set()
    for batch in batches:  # and no later batch repeats a row of any earlier one
        rows = set(map(tuple, batch["rows"]))
        assert not rows & seen, (rows & seen, [len(b["rows"]) for b in batches])  # C1
        seen |= rows

    empty = next((i for i, b in enumerate(batches) if not b["rows"]), None)
    # the seed's pool ends within the budget, with at least one call after it to count
    assert empty is not None and empty + 1 < len(batches), [len(b["rows"]) for b in batches]  # C1
    sizes = [len(b["rows"]) for b in batches]
    assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes  # C1
    # control: up to the empty batch, every batch was one request through the given fetch
    assert [b["calls"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches
    assert all(b["calls"] == batches[empty]["calls"] for b in batches[empty + 1:]), batches  # C1
    # the size follows the limit sent: the similars default is also 48, so a dropped limit reads 48 here
    short = _run(tmp_path, engine_client.base, seed, page="20", max_batches=2)
    assert [len(b.get("rows", [])) for b in short] == [20, 20], short  # C1


def test_the_durable_pager_test_passes_a_pager_that_holds_the_contract_and_fails_one_that_repeats_keeps_asking_or_never_runs_dry(tmp_path):
    assert DURABLE.is_file(), DURABLE  # C1
    durable = _load(DURABLE, "durable_upnext_pager")
    assert [n for n in vars(durable) if n.startswith("test_")], sorted(vars(durable))
    flat = [1, 2, 3, 4, 5, 6, 7, 8, 8, 8]
    # control: the batches the live run above observed pass, so a failure below is the durable assertions firing
    assert not _fails(durable, _canned([48] * 6 + [12, 0, 0, 0], flat), tmp_path)
    repeat = _canned([48] * 6 + [12, 0, 0, 0], flat)
    repeat[3]["rows"][0] = repeat[0]["rows"][0]
    wrong = {
        "repeats a row of an earlier batch": repeat,
        "never runs dry": _canned([48] * 10, range(1, 11)),
        "keeps asking after the empty batch": _canned([48] * 6 + [12, 0, 0, 0], range(1, 11)),
        "resolves to another mode": _canned([48] * 6 + [12, 0, 0, 0], flat, mode="random"),
        "returns an empty second batch": _canned([48] + [0] * 9, [1] + [2] * 9),
        "crashes partway": _canned([48] * 5, [1, 2, 3, 4, 5]) + [{"error": "TypeError: fetch failed", "calls": 5}],
    }
    assert [label for label, batches in wrong.items() if not _fails(durable, batches, tmp_path)] == []  # C1


def test_the_durable_pager_group_is_fingerprinted_over_videos_ts_the_client_server_and_both_engine_similars_files():
    harness = _load(HARNESS, "validate_tests")
    claims = harness.claimed(ROOT, harness.load_config())
    # control: groups are discovered from tests/active and carry their mapped files
    assert ROOT / "client/frontend/src/pages/video-page/index.ts" in claims.get("test_frontend_video_page.py", []), sorted(claims)
    # control: every subject exists, so one missing from the claim is a mapping gap and not a typo here
    assert [s for s in SUBJECTS if not (ROOT / s).is_file()] == []
    covered = claims.get("test_frontend_upnext_pager.py")
    assert covered is not None, sorted(claims)  # C1
    assert [s for s in SUBJECTS if ROOT / s not in covered] == [], covered  # C1
