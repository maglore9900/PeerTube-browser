"""Probe: what the page-fit runner reports for the feed, search and up-next pages, on today's tree and on the draft applied to a copy."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_frontend_tag_chips as checkpoint  # noqa: E402
from probe_54_p4_vs_draft import _patch  # noqa: E402


def _bundles(out: Path, src: Path) -> Path:
    out.mkdir(parents=True)
    checkpoint._build(out, "page.mjs", dev=False, entry=src / "pages" / "video-page" / "index.ts")
    checkpoint._build(out, "feed.mjs", dev=False, entry=src / "pages" / "videos" / "index.ts")
    checkpoint._build(out, "search.mjs", dev=False, entry=src / "pages" / "search" / "index.ts")
    (out / "page_fit.mjs").write_text(checkpoint.PAGE_FIT_RUNNER)
    return out


def test_probe(tmp_path):
    root = tmp_path / "draft"
    src = root / "frontend" / "src"
    shutil.copytree(checkpoint.FRONTEND / "src", src)
    (root / "frontend" / "node_modules").symlink_to(checkpoint.FRONTEND / "node_modules")
    _patch(src)
    trees = {"today": _bundles(tmp_path / "today", checkpoint.FRONTEND / "src"), "draft": _bundles(tmp_path / "draft_out", src)}
    seen = {}
    for name, out in trees.items():
        for page in checkpoint.PAGES:
            try:
                report = checkpoint._page_fit(out, page)
            except AssertionError as error:
                seen[f"{name}/{page}"] = f"node failed: {str(error)[:1500]}"
                continue
            seen[f"{name}/{page}"] = {"bench": report["bench"], "requested": report["requested"], "errors": [e[:300] for e in report["errors"]], "snapshots": report["snapshots"]}
    assert False, json.dumps(seen, indent=1)
