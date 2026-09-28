"""Probe: is phase 3's red the runner's stdout cut at the pipe buffer when node exits right after write?"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_12_similars_on_scroll_phase3 as t

out = Path(tempfile.mkdtemp())
subprocess.run([str(t.ESBUILD), str(t.FRONTEND / "src/pages/video-page/index.ts"), "--bundle", "--format=esm", "--platform=node",
                "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
                f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(t.BASE)}", "--define:import.meta.env.DEV=false"],
               check=True, capture_output=True)
drained = t.RUNNER.replace('+ "\\n");\nprocess.exit(0);', '+ "\\n", () => process.exit(0));')
assert drained != t.RUNNER
answers = [{"rows": t._rows("v"), "seed": {"mode": "upnext"}}, {"rows": t._rows("w"), "seed": {"mode": "upnext"}}]
env = {"BASE": t.BASE, "BUNDLE": str(out / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
       "RECOMMENDATIONS_BODIES": json.dumps(answers), "INTERSECTIONS": str(t.INTERSECTIONS)}
for name, runner in [("as-is", t.RUNNER), ("drained", drained)]:
    (out / "runner.mjs").write_text(runner)
    proc = subprocess.run(["node", str(out / "runner.mjs")], capture_output=True, env=env, timeout=60)
    raw = proc.stdout
    try:
        json.loads(raw.splitlines()[-1]); ok = "parses"
    except Exception as e:
        ok = f"fails: {type(e).__name__}"
    print(f"{name}: exit={proc.returncode} stdout_bytes={len(raw)} {ok}")
