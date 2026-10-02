"""The committed `client/frontend/dist/` is a current build of the frontend sources: rebuild and commit it with any source change.

With no local `dev-pages/about.html`, a fresh `vite build --outDir <tmp>` emits exactly the asset file names the committed dist holds (they are content-hashed, so a source change without a rebuild shows here), and each of the seven HTML pages exactly as committed (pages carry no hash, so a hand-edited page shows here). Control: the committed About page is the template build, not a local override.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
DIST = FRONTEND / "dist"
VITE = FRONTEND / "node_modules" / ".bin" / "vite"
PAGES = ("index.html", "videos.html", "likes.html", "search.html", "video-page.html", "channels.html", "dev-pages/about.template.html")


def test_the_committed_dist_holds_exactly_the_assets_a_fresh_build_emits_and_no_about_override(tmp_path):
    assert not (FRONTEND / "dev-pages" / "about.html").exists(), "a local dev-pages/about.html replaces the About template in the build; move it aside before running"
    out = tmp_path / "dist"
    built = subprocess.run([str(VITE), "build", "--outDir", str(out)], cwd=FRONTEND, capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    # control: the committed About page is the template build, not a local override
    assert not (DIST / "dev-pages" / "about.html").exists()
    assert sorted(p.name for p in (DIST / "assets").iterdir()) == sorted(p.name for p in (out / "assets").iterdir()), "client/frontend/dist is stale; run the frontend build and commit dist"
    assert [page for page in PAGES if (DIST / page).read_text() != (out / page).read_text()] == [], "a committed dist page differs from a fresh build"
