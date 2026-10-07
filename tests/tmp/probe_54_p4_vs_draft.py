"""Probe: the checkpoint's tests against the plan's Phase 4 draft, applied to a copy of client/frontend/src in tmp (the real tree is untouched)."""
from __future__ import annotations

import inspect
import re
import shutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_frontend_tag_chips as checkpoint  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PLAN = (ROOT / "docs" / "project" / "plans" / "54-53-tags-on-cards-and-tag.md").read_text()


def _fence_after(marker: str) -> str:
    start = PLAN.index(marker)
    body = PLAN.index("```ts\n", start) + len("```ts\n")
    return PLAN[body:PLAN.index("```", body)]


def _patch(src: Path) -> None:
    card = src / "components" / "video-card.ts"
    text = card.read_text()
    text = text.replace("/**\n * Render one video card as HTML.", _fence_after("New code goes after `videoPageUrl`") + "\n/**\n * Render one video card as HTML.", 1)
    assert "</a>${actionsMarkup}" in text
    text = text.replace("</a>${actionsMarkup}", "</a>${renderTagChips(row.tags, options.apiParam)}${actionsMarkup}")
    card.write_text(text)
    page = src / "pages" / "video-page" / "index.ts"
    text = page.read_text()
    text = text.replace('import { followLabel } from "../../components/video-card";', 'import { followLabel, observeTagRows, renderTagChips, tagSearchUrl } from "../../components/video-card";')
    text = text.replace("const params = new URLSearchParams(window.location.search);\n", "const params = new URLSearchParams(window.location.search);\nif (similarCards) observeTagRows(similarCards);\n", 1)
    old_tags = re.search(r"      // Tags come from remote instances, so each chip is built from text, never from markup\.\n      tagsEl\.replaceChildren\(\n.*?\n      \);\n", text, re.S)
    assert old_tags
    text = text.replace(old_tags.group(0), _fence_after("- Tag chips (290-300):").rstrip("\n") + "\n")
    old_card = re.search(r"  return `\n    <a class=\"similar-card-item\".*?\n  `;\n", text, re.S)
    assert old_card
    text = text.replace(old_card.group(0), _fence_after("`renderSimilarCard`:"))
    page.write_text(text)
    # The draft's feed wiring (after the guard at 66-68) and search wiring (after the results click listener).
    feed = src / "pages" / "videos" / "index.ts"
    text = feed.read_text()
    text = text.replace("  renderVideoCard,\n", "  observeTagRows,\n  renderVideoCard,\n", 1)
    text = text.replace('  throw new Error("Missing videos elements");\n}\n', '  throw new Error("Missing videos elements");\n}\nobserveTagRows(cards);\n', 1)
    feed.write_text(text)
    search = src / "pages" / "search" / "index.ts"
    text = search.read_text()
    text = text.replace("  renderVideoCard,\n", "  observeTagRows,\n  renderVideoCard,\n", 1)
    text = text.replace("  if (button && card && row) void runCardAction(button, card, row);\n});\n", "  if (button && card && row) void runCardAction(button, card, row);\n});\nobserveTagRows(results);\n", 1)
    search.write_text(text)


LOOP = """  let hidden = 0;
  while (hidden < chips.length && row.scrollWidth > row.clientWidth) {
    hidden += 1;
    chips[chips.length - hidden].hidden = true;
    more.textContent = `+${hidden}`;
    more.setAttribute("aria-label", `${hidden} more ${hidden === 1 ? "tag" : "tags"}`);
    more.hidden = false;
  }
"""
# A fit that sums chip widths against the row instead of reading scrollWidth; OP is the comparison an exact fit turns on.
SUM = """  const widths = chips.map((chip) => chip.offsetWidth);
  if (widths.reduce((a, b) => a + b, 0) OP row.clientWidth) return;
  more.hidden = false;
  const room = row.clientWidth - more.offsetWidth;
  let used = 0;
  let shown = 0;
  while (shown < chips.length && used + widths[shown] OP room) { used += widths[shown]; shown += 1; }
  const hidden = chips.length - shown;
  chips.slice(shown).forEach((chip) => { chip.hidden = true; });
  more.textContent = `+${hidden}`;
  more.setAttribute("aria-label", `${hidden} more ${hidden === 1 ? "tag" : "tags"}`);
"""

CARD = "components/video-card.ts"
PAGE = "pages/video-page/index.ts"
FEED = "pages/videos/index.ts"
SEARCH = "pages/search/index.ts"
MUTANTS = {
    "draft": [],
    "utf16-length": [(CARD, "Array.from(value).length > TAG_MAX_LENGTH", "value.length > TAG_MAX_LENGTH")],
    "api-always": [(CARD, 'if (apiParam && import.meta.env.DEV) params.set("api", apiParam);\n  return `/search.html', 'if (apiParam) params.set("api", apiParam);\n  return `/search.html')],
    "no-trim": [(CARD, "const value = tag.trim();", "const value = tag;")],
    "no-limit": [(CARD, "!value || Array.from(value).length > TAG_MAX_LENGTH", "!value")],
    "row-inside-link": [(CARD, "</a>${renderTagChips(row.tags, options.apiParam)}", "${renderTagChips(row.tags, options.apiParam)}</a>")],
    "marker-shown": [(CARD, '<span class="tag-more" hidden></span>', '<span class="tag-more"></span>')],
    "unescaped": [(CARD, "${escapeHtml(tag)}</a>`", "${tag}</a>`")],
    "chips-ignore-api": [(CARD, "const href = tagSearchUrl(tag, apiParam);", "const href = tagSearchUrl(tag);")],
    "sorted": [(CARD, "const chips = tags.flatMap(", "const chips = [...tags].sort().flatMap(")],
    "no-unhide": [(CARD, "for (const chip of chips) chip.hidden = false;", "")],
    "hide-from-start": [(CARD, "chips[chips.length - hidden].hidden = true;", "chips[hidden - 1].hidden = true;")],
    "similar-link-wraps-row": [(PAGE, "      </a>\n      ${renderTagChips(row.tags, params.get(\"api\"))}", "      ${renderTagChips(row.tags, params.get(\"api\"))}\n      </a>")],
    "page-always-link": [(PAGE, 'document.createElement(href ? "a" : "span")', 'document.createElement("a")')],
    "marker-first": [(CARD, '<div class="card-tags">${chips.join("")}<span class="tag-more" hidden></span></div>', '<div class="card-tags"><span class="tag-more" hidden></span>${chips.join("")}</div>')],
    "sum-le (a valid fit)": [(CARD, LOOP, SUM.replace("OP", "<="))],
    "sum-lt": [(CARD, LOOP, SUM.replace("OP", "<"))],
    "keep-one": [(CARD, "while (hidden < chips.length &&", "while (hidden < chips.length - 1 &&")],
    "first-batch-only": [(CARD, "  new MutationObserver((records) => {\n    for", "  let tagRowsSeen = false;\n  new MutationObserver((records) => {\n    if (tagRowsSeen) return;\n    tagRowsSeen = true;\n    for")],
    "feed-not-wired": [(FEED, "observeTagRows(cards);\n", "")],
    "search-not-wired": [(SEARCH, "observeTagRows(results);\n", "")],
    "upnext-not-wired": [(PAGE, "if (similarCards) observeTagRows(similarCards);\n", "")],
}


def _run(tmp_path: Path, name: str, mutations: list) -> dict:
    root = tmp_path / name
    src = root / "frontend" / "src"
    shutil.copytree(checkpoint.FRONTEND / "src", src)
    (root / "frontend" / "node_modules").symlink_to(checkpoint.FRONTEND / "node_modules")
    _patch(src)
    for rel, old, new in mutations:
        path = src / rel
        text = path.read_text()
        assert old in text, (name, old)
        path.write_text(text.replace(old, new))
    out = root / "bundles"
    out.mkdir()
    checkpoint._build(out, "card_prod.mjs", dev=False, entry=src / "components" / "video-card.ts")
    checkpoint._build(out, "card_dev.mjs", dev=True, entry=src / "components" / "video-card.ts")
    checkpoint._build(out, "page.mjs", dev=False, entry=src / "pages" / "video-page" / "index.ts")
    checkpoint._build(out, "feed.mjs", dev=False, entry=src / "pages" / "videos" / "index.ts")
    checkpoint._build(out, "search.mjs", dev=False, entry=src / "pages" / "search" / "index.ts")
    for file, runner in [("call.mjs", checkpoint.CALL_RUNNER), ("fit.mjs", checkpoint.FIT_RUNNER), ("video.mjs", checkpoint.VIDEO_PAGE_RUNNER), ("similars.mjs", checkpoint.SIMILARS_RUNNER), ("page_fit.mjs", checkpoint.PAGE_FIT_RUNNER)]:
        (out / file).write_text(runner)
    outcome = {}
    for test, fn in inspect.getmembers(checkpoint, inspect.isfunction):
        if not test.startswith("test_"):
            continue
        cases = [(f"[{page}]", {"page": page}) for page in checkpoint.PAGES] if "page" in inspect.signature(fn).parameters else [("", {})]
        for suffix, kwargs in cases:
            try:
                fn(out, **kwargs)
            except BaseException:
                tb = traceback.extract_tb(sys.exc_info()[2])
                line = [frame for frame in tb if frame.filename.endswith("test_frontend_tag_chips.py")][-1]
                outcome[test[5:60] + suffix] = f"line {line.lineno}: {line.line[-40:]}"
    return outcome


def test_probe(tmp_path):
    report = {name: _run(tmp_path, name, mutations) for name, mutations in MUTANTS.items()}
    assert False, "\n".join(f"{name}: {outcome or 'ALL PASS'}" for name, outcome in report.items())
