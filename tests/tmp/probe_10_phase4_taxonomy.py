"""Probe: the phase-4 harness against the current page, and against two hand-written plausible taxonomy renderers (right and wrong)."""
import importlib.util
import json
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("phase4", Path(__file__).with_name("test_10_video_metadata_completeness_phase4.py"))
phase4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase4)

CASES = [({"category": "Science & Technology", "language": "English", "tags": ["alpha", "beta"]}, phase4.ITEMS), ({"category": "", "language": "", "tags": []}, []), ({"category": "Music", "language": "", "tags": ["solo"]}, ["video-category"])]

RIGHT = """
const data = await (await fetch("/api/video")).json();
document.getElementById("video-title").textContent = data.title;
const show = (item, valueId, value) => { document.getElementById(item).hidden = !value; document.getElementById(valueId).textContent = value; };
show("video-category", "video-category-value", data.category);
show("video-language", "video-language-value", data.language);
const tags = document.getElementById("video-tags");
if (data.tags.length) tags.replaceChildren(...data.tags.map((t) => { const c = document.createElement("span"); c.className = "tag-chip"; c.textContent = t; return c; }));
else tags.textContent = "No tags";
"""

WRONG = """
const data = await (await fetch("/api/video")).json();
document.getElementById("video-title").textContent = data.title;
document.getElementById("video-category").removeAttribute("hidden");
document.getElementById("video-category-value").textContent = data.category;
document.getElementById("video-language").hidden = !data.category;
document.getElementById("video-language-value").textContent = data.language;
document.getElementById("video-tags").innerHTML = data.tags.map((t) => `<span class="tag-chip">${t}</span>`).join("") || "No tags";
"""


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
        print("CURRENT", body, phase4._page(tmp_path, body, hidden))
    for name, source in [("RIGHT", RIGHT), ("WRONG", WRONG)]:
        impl = tmp_path / name
        impl.mkdir()
        (impl / "bundle.mjs").write_text(source)
        (impl / "runner.mjs").write_text(phase4.RUNNER)
        for body, hidden in CASES:
            print(name, body, phase4._page(impl, body, hidden))
    assert False, "probe"
