"""Probe: the fit harness (layout, MutationObserver and ResizeObserver stubs) against the draft's observeTagRows, copied here, and two wrong variants."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_frontend_tag_chips import CARD_ROWS_FIT, FIT_RUNNER, RESIZES, _build  # noqa: E402

REFERENCE = """
import * as real from "./card_prod.mjs";
const VARIANT = process.env.VARIANT;
const row = (tags) => `<div class="card-tags">${tags.map((t) => `<a class="tag-chip" href="/search.html?tag=${t}">${t}</a>`).join("")}<span class="tag-more" hidden></span></div>`;
export function renderVideoCard(r, o) { return real.renderVideoCard(r, o).replace("</article>", row(r.tags) + "</article>"); }
function fitTagRow(row) {
  const chips = Array.from(row.querySelectorAll(".tag-chip"));
  const more = row.querySelector(".tag-more");
  if (!more) return;
  if (VARIANT !== "no-unhide") for (const chip of chips) chip.hidden = false;
  more.hidden = true;
  let hidden = chips.filter((c) => c.hidden).length;
  if (VARIANT === "marker-after") {
    while (hidden < chips.length && row.scrollWidth > row.clientWidth) { hidden += 1; chips[chips.length - hidden].hidden = true; }
    if (hidden) { more.textContent = `+${hidden}`; more.setAttribute("aria-label", `${hidden} more ${hidden === 1 ? "tag" : "tags"}`); more.hidden = false; }
    return;
  }
  if (hidden) { more.textContent = `+${hidden}`; more.hidden = false; }
  while (hidden < chips.length && row.scrollWidth > row.clientWidth) {
    hidden += 1;
    chips[chips.length - hidden].hidden = true;
    more.textContent = `+${hidden}`;
    more.setAttribute("aria-label", `${hidden} more ${hidden === 1 ? "tag" : "tags"}`);
    more.hidden = false;
  }
}
let tagRowResizer = null;
const fittedWidths = new WeakMap();
export function observeTagRows(container) {
  if (typeof MutationObserver === "undefined" || typeof ResizeObserver === "undefined") return;
  tagRowResizer ??= new ResizeObserver((entries) => {
    for (const entry of entries) {
      const width = entry.contentRect.width;
      if (fittedWidths.get(entry.target) === width) continue;
      fittedWidths.set(entry.target, width);
      fitTagRow(entry.target);
    }
  });
  const resizer = tagRowResizer;
  const rowsIn = (node) => node instanceof HTMLElement ? node.matches(".card-tags") ? [node] : Array.from(node.querySelectorAll(".card-tags")) : [];
  for (const row of rowsIn(container)) resizer.observe(row);
  new MutationObserver((records) => {
    for (const record of records) {
      record.addedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.observe(row)));
      record.removedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.unobserve(row)));
    }
  }).observe(container, { childList: true, subtree: true });
}
"""


def test_probe(tmp_path):
    _build(tmp_path, "card_prod.mjs", dev=False)
    (tmp_path / "reference.mjs").write_text(REFERENCE)
    (tmp_path / "fit.mjs").write_text(FIT_RUNNER)
    seen = {}
    for variant, bundle in [("today", "card_prod.mjs"), ("draft", "reference.mjs"), ("marker-after", "reference.mjs"), ("no-unhide", "reference.mjs")]:
        proc = subprocess.run(["node", str(tmp_path / "fit.mjs")], capture_output=True, text=True, timeout=60,
                              env={"PATH": os.environ.get("PATH", ""), "BUNDLE": str(tmp_path / bundle), "VARIANT": variant, "CARDS": json.dumps(CARD_ROWS_FIT), "RESIZES": json.dumps(RESIZES)})
        report = json.loads(proc.stdout.splitlines()[-1]) if proc.stdout.strip() else None
        brief = [{k: (v and (v["visible"], [(m["hidden"], m["text"], m["label"]) for m in v["markers"]], v["scroll"], v["width"])) for k, v in snap.items()} for snap in report["snapshots"]] if report else None
        seen[variant] = (proc.returncode, proc.stderr[-800:], report and report["observeError"], report and report["errors"], brief)
    assert False, json.dumps(seen, indent=1)
