"""Probe: the fit runner on the draft (applied to a copy) and wrong variants, with an appended five-chip card and the stub's exact-fit widths."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_frontend_tag_chips as checkpoint  # noqa: E402
from probe_54_p4_vs_draft import LOOP, SUM, _patch  # noqa: E402

LATE = "tags.example::late"
CARDS = [
    {"key": checkpoint.FIVE, "width": 160, "row": {"video_uuid": "five", "instance_domain": "tags.example", "title": "Five tags", "tags": ["t1", "t2", "t3", "t4", "t5"]}},
    {"key": checkpoint.FITS, "width": 160, "row": {"video_uuid": "fits", "instance_domain": "tags.example", "title": "Two tags", "tags": ["solo", "duo"]}},
    {"key": LATE, "width": 160, "row": {"video_uuid": "late", "instance_domain": "tags.example", "title": "Late five", "tags": ["t1", "t2", "t3", "t4", "t5"]}},
]
RESIZES = checkpoint.RESIZES
CARD = "components/video-card.ts"
VARIANTS = {
    "draft": [],
    "strict": [(CARD, "row.scrollWidth > row.clientWidth", "row.scrollWidth >= row.clientWidth")],
    "sum-le": [(CARD, LOOP, SUM.replace("OP", "<="))],
    "sum-lt": [(CARD, LOOP, SUM.replace("OP", "<"))],
    "keep-one": [(CARD, "while (hidden < chips.length &&", "while (hidden < chips.length - 1 &&")],
    "first-batch-only": [(CARD, "  new MutationObserver((records) => {\n    for", "  let tagRowsSeen = false;\n  new MutationObserver((records) => {\n    if (tagRowsSeen) return;\n    tagRowsSeen = true;\n    for")],
}


def test_probe(tmp_path):
    seen = {}
    for name, mutations in VARIANTS.items():
        root = tmp_path / name
        src = root / "frontend" / "src"
        shutil.copytree(checkpoint.FRONTEND / "src", src)
        (root / "frontend" / "node_modules").symlink_to(checkpoint.FRONTEND / "node_modules")
        _patch(src)
        for rel, old, new in mutations:
            text = (src / rel).read_text()
            assert old in text, (name, old)
            (src / rel).write_text(text.replace(old, new))
        out = root / "out"
        out.mkdir()
        checkpoint._build(out, "card_prod.mjs", dev=False, entry=src / "components" / "video-card.ts")
        (out / "fit.mjs").write_text(checkpoint.FIT_RUNNER)
        report = checkpoint._node(out / "fit.mjs", {"BUNDLE": str(out / "card_prod.mjs"), "CARDS": json.dumps(CARDS), "RESIZES": json.dumps(RESIZES)})
        seen[name] = {"cards": report["cards"], "errors": report["errors"], "observeError": report["observeError"],
                      "snapshots": [{k: v and (v["visible"], [(m["hidden"], m["text"], m["label"]) for m in v["markers"]], v["width"], v["scroll"]) for k, v in s.items()} for s in report["snapshots"]]}
    assert False, json.dumps(seen)
