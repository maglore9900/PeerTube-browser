import subprocess
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"


def test_bundles_and_resolves(tmp_path):
    entry = tmp_path / "e.ts"
    entry.write_text(f'export {{ FEED_MODES, resolveFeedParams, persistFeedParams }} from "{FRONTEND}/src/data/feed-params.ts";\nexport {{ buildSimilarUrl }} from "{FRONTEND}/src/data/videos.ts";\n')
    out = tmp_path / "b.mjs"
    run = subprocess.run([str(FRONTEND / "node_modules/.bin/esbuild"), str(entry), "--bundle", "--format=esm", "--platform=node", f"--outfile={out}", '--define:import.meta.env.VITE_CLIENT_API_BASE="http://c.test"', "--define:import.meta.env.DEV=false"], capture_output=True, text=True)
    print(run.stderr)
    assert run.returncode == 0
    runner = tmp_path / "r.mjs"
    runner.write_text(f"""
const s = new Map(); const m = {{ getItem: k => s.has(k) ? s.get(k) : null, setItem: (k, v) => s.set(k, String(v)) }};
globalThis.localStorage = m; globalThis.sessionStorage = m; globalThis.window = {{ location: {{ origin: "http://c.test" }}, localStorage: m }};
const b = await import("{out}");
const u = (q) => b.buildSimilarUrl({{ limit: "12" }}, b.resolveFeedParams(new URLSearchParams(q)));
console.log(JSON.stringify(b.FEED_MODES), u("?mode=hot&random=1"), u("?random=1"), u(""), u("?mode=bogus"));
b.persistFeedParams({{ mode: "recent" }}); console.log(u(""), b.buildSimilarUrl({{ limit: "12" }}));
""")
    r = subprocess.run(["node", str(runner)], capture_output=True, text=True)
    print(r.stdout, r.stderr)
    assert r.returncode == 0
