"""The frontend's feed pager over up-next similars, run in node against the real Client and Engine at the video page's 48-row batch: its batches never repeat a row, and it stops asking once a batch adds nothing.

- For the linux seed, the pager's first batch is an up-next page, its second batch holds rows and none of the first batch's, and no later batch repeats a row of an earlier one. Each batch is a random draw (build 09), so no two pages are compared for equality.
- The pager is driven for MAX_BATCHES calls and reaches an empty batch before the last: the Engine takes a seed's top 300 rows before it drops excluded ones, so at 48 a batch the pool runs out in about 7. No call after the empty batch makes a request, counted on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).
- Every batch before the last non-empty one holds exactly 48 rows, and that one holds 1 to 48. The similars default is also 48, so a second run of the same seed at limit 20 for 2 batches must come back 20 x 2: the batch size follows the `limit` sent, not the default.

Replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones, as `test_frontend_video_page.py` does.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
PAGE = "48"
MAX_BATCHES = 10

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


def test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(
        engine_client, tmp_path):
    seed = _seed(engine_client)
    batches = _run(tmp_path, engine_client.base, seed)
    assert all("error" not in b for b in batches), batches
    assert len(batches) == MAX_BATCHES, batches
    assert batches[0]["mode"] == "upnext", batches[0]  # control: the seed resolves to up-next

    first, second = (set(map(tuple, b["rows"])) for b in batches[:2])
    assert first, "the first batch is empty"
    assert second, "the second batch is empty"
    assert not first & second, first & second
    seen: set[tuple] = set()
    for batch in batches:  # and no later batch repeats a row of any earlier one
        rows = set(map(tuple, batch["rows"]))
        assert not rows & seen, (rows & seen, [len(b["rows"]) for b in batches])
        seen |= rows

    empty = next((i for i, b in enumerate(batches) if not b["rows"]), None)
    # the seed's pool ends within the budget, with at least one call after it to count
    assert empty is not None and empty + 1 < len(batches), [len(b["rows"]) for b in batches]
    sizes = [len(b["rows"]) for b in batches]
    assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes
    # control: up to the empty batch, every batch was one request through the given fetch
    assert [b["calls"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches
    assert all(b["calls"] == batches[empty]["calls"] for b in batches[empty + 1:]), batches
    # the size follows the limit sent: the similars default is also 48, so a dropped limit reads 48 here
    short = _run(tmp_path, engine_client.base, seed, page="20", max_batches=2)
    assert [len(b.get("rows", [])) for b in short] == [20, 20], short
