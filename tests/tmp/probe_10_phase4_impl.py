"""Probe: what the edited video page renders for the three taxonomy bodies under the phase-4 harness."""
import importlib.util
import json
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("phase4", Path(__file__).with_name("test_10_video_metadata_completeness_phase4.py"))
phase4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase4)

CASES = [({"category": "Science & Technology", "language": "English", "tags": ["alpha", "beta"]}, phase4.ITEMS), ({"category": "", "language": "", "tags": []}, []), ({"category": "Music", "language": "", "tags": ["solo"]}, ["video-category"])]


def test_probe(tmp_path):
    proc = subprocess.run(
        [str(phase4.ESBUILD), str(phase4.FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={tmp_path / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(phase4.BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    print("ESBUILD", proc.returncode, proc.stderr)
    (tmp_path / "runner.mjs").write_text(phase4.RUNNER)
    for body, hidden in CASES:
        print("PAGE", body, json.dumps(phase4._page(tmp_path, body, hidden)))
    assert False, "probe"
