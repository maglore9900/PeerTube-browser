"""Probe: with the runner draining stdout before exit, does phase 3's checkpoint assertion hold against the phase 3 code?"""
import json, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_12_similars_on_scroll_phase3 as t

t.RUNNER = t.RUNNER.replace('+ "\\n");\nprocess.exit(0);', '+ "\\n", () => process.exit(0));')
out = Path(tempfile.mkdtemp())
subprocess.run([str(t.ESBUILD), str(t.FRONTEND / "src/pages/video-page/index.ts"), "--bundle", "--format=esm", "--platform=node",
                "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
                f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(t.BASE)}", "--define:import.meta.env.DEV=false"],
               check=True, capture_output=True)
(out / "runner.mjs").write_text(t.RUNNER)
try:
    t.test_each_sentinel_intersection_appends_the_next_8_rows_and_the_one_after_all_48_asks_for_a_batch_excluding_them(out)
    print("PASS with drained runner")
except AssertionError as e:
    print("FAIL:", str(e)[:1500])
