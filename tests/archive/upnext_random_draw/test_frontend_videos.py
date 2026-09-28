"""Retired whole from `tests/active/test_frontend_videos.py` in build 09-similars-diversity (plan 19), step 8.

It conflicts with two confirmed requirements of that build. Phase 3 C1 makes an up-next page a random score-weighted draw, so two plain fetches no longer return the same page (the control at its old line 87). Phase 2 C1 fills a short pool past one 48-row batch, so the linux pool, measured at 19 deep when this was written, now holds up to 300 rows, and no batch of 8 comes back empty within MAX_BATCHES = 6 (line 101). The pinned rewrite in plan §7h was never written; issue 35 tracks a replacement. Kept verbatim below the line for reference; it skips.

---

The frontend's feed pager, run in node against the real Client and Engine: its batches never
repeat a row, and it stops asking once a batch adds nothing.

- In up-next mode for a seed whose ranked pool is deeper than one 8-row page, the pager's second
  batch holds rows and none of the first batch's, and no later batch repeats a row of an
  earlier one, where two plain fetches return the same page.
- The pager is driven until a batch comes back empty; no call after it makes a request, counted
  on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).

`window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner
supplies minimal in-memory ones, as `test_frontend_blocks.py` does.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

FRONTEND = Path(__file__).resolve().parents[3] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
PAGE = "8"
MAX_BATCHES = 6

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
const m = await import(process.env.BUNDLE);
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\\n");
const keys = (rows) => (rows ?? []).map((r) => [r.video_id, r.instance_domain]);
const query = { id: process.env.SEED_UUID, host: process.env.SEED_HOST, limit: process.env.PAGE,
  apiBase: process.env.BASE };
for (let i = 0; i < 2; i += 1) {
  const plain = await m.fetchSimilarVideosPayload(query);
  say({ plain: keys(plain.rows), mode: plain.seed?.mode ?? null });
}
let calls = 0;
try {
  const pager = m.createFeedPager((exclude) => { calls += 1; return m.fetchSimilarVideosPayload(query, exclude); });
  for (let i = 0; i < Number(process.env.MAX_BATCHES); i += 1) {
    const payload = await pager.next();
    say({ rows: keys(payload.rows), calls });
  }
} catch (e) { say({ error: String(e) }); }
process.exit(0);
"""


def _run(tmp_path: Path, base: str, seed: dict) -> list[dict]:
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
             "PAGE": PAGE, "MAX_BATCHES": str(MAX_BATCHES)},
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def _seed(client) -> dict:
    # A seed whose up-next pool was 19 deep when measured (`probe_upnext_repeat.py`).
    status, body = client.request("GET", "/api/v1/search/videos?q=linux&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def test_the_pager_s_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(
        engine_client, tmp_path):
    out = _run(tmp_path, engine_client.base, _seed(engine_client))
    plain_a, plain_b, *batches = out
    assert plain_a["mode"] == "upnext", plain_a  # control: the seed resolves to up-next
    assert plain_a["plain"] and plain_a["plain"] == plain_b["plain"], "control: a plain fetch does not repeat"
    assert all("error" not in b for b in batches), batches

    first, second = (set(map(tuple, b["rows"])) for b in batches[:2])
    assert first, "the first batch is empty"
    assert second, "the second batch is empty"  # C1
    assert not first & second, first & second  # C1
    seen: set[tuple] = set()
    for batch in batches:  # and no later batch repeats a row of any earlier one
        rows = set(map(tuple, batch["rows"]))
        assert not rows & seen, (rows & seen, batches)
        seen |= rows

    empty = next((i for i, b in enumerate(batches) if not b["rows"]), None)
    assert empty is not None and empty + 1 < len(batches), batches  # the pager reached an empty batch
    # control: up to the empty batch, every batch was one request through the given fetch
    assert [b["calls"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches
    assert all(b["calls"] == batches[empty]["calls"] for b in batches[empty + 1:]), batches  # C2
