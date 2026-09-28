"""Probe: what the second request body looks like when the real pager drives fetchSimilarVideosPayload."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"

RUNNER = """
const memory = () => { const s = new Map(); return { getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage };
const requests = [];
const answers = JSON.parse(process.env.BODIES);
let n = 0;
globalThis.fetch = async (input, init) => { const url = new URL(String(input), process.env.BASE); requests.push({ method: init?.method, path: url.pathname, query: Object.fromEntries(url.searchParams), body: init?.body ? JSON.parse(init.body) : null }); return new Response(JSON.stringify(answers[n++] ?? { rows: [] }), { status: 200, headers: { "content-type": "application/json" } }); };
const m = await import(process.env.BUNDLE);
const pager = m.createFeedPager((exclude) => m.fetchSimilarVideosPayload({ id: "v1", host: "peer.example", limit: "48", apiBase: process.env.BASE }, exclude));
await pager.next();
await pager.next();
process.stdout.write(JSON.stringify(requests) + "\\n");
process.exit(0);
"""


def test_probe(tmp_path):
    entry = tmp_path / "entry.ts"
    entry.write_text(f'export {{ createFeedPager, fetchSimilarVideosPayload }} from "{FRONTEND}/src/data/videos.ts";\n')
    subprocess.run([str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", f"--outfile={tmp_path / 'bundle.mjs'}", f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"], check=True, capture_output=True)
    (tmp_path / "runner.mjs").write_text(RUNNER)
    rows = lambda p: [{"video_id": f"{p}{i}", "instance_domain": "videos.example"} for i in range(48)]
    proc = subprocess.run(["node", str(tmp_path / "runner.mjs")], capture_output=True, text=True, timeout=60, env={"BASE": BASE, "BUNDLE": str(tmp_path / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "BODIES": json.dumps([{"rows": rows("v")}, {"rows": rows("w")}])})
    requests = json.loads(proc.stdout.splitlines()[-1])
    second = requests[1]
    print("METHOD", second["method"], "PATH", second["path"], "KEYS", sorted(second["body"]), "N", len(second["body"].get("exclude", [])), "FIRST3", second["body"].get("exclude", [])[:3], "FIRST_BODY_KEYS", sorted(requests[0]["body"]))
    assert False, "probe: read the printed line"
