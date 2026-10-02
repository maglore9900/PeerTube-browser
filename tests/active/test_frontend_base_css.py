"""Every page CSS bundle Vite builds opens with the shared rules of `src/base.css`, inlined, then carries that page's own rules.

`vite build --outDir <tmp>` runs in `client/frontend` with no local `dev-pages/about.html` to replace the About template. Every CSS bundle linked from the built HTML (exactly the videos, video, channels and search bundles) contains no `@import`, opens on `:root` with `--paper`, and its leading rules (selector and declarations, media blocks included) equal, rule for rule, the rules of `src/base.css` built alone through the same Vite config; each bundle also holds page rules after that prefix. A page sheet that drops its `@import "./base.css"` loses the colour tokens and the shared layout on its page.
"""
from __future__ import annotations

import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
VITE = FRONTEND / "node_modules" / ".bin" / "vite"
VITE_API = FRONTEND / "node_modules" / "vite" / "dist" / "node" / "index.js"

# Builds one stylesheet alone through the project's own Vite config, so the base passes through the same minifier as the page bundles.
SINGLE_SHEET_BUILD = """
const { build } = await import(process.env.VITE_API);
await build({ configFile: process.env.CONFIG, root: process.env.FRONTEND, logLevel: "silent", build: { outDir: process.env.OUT, emptyOutDir: true, rollupOptions: { input: process.env.INPUT } } });
"""

Rule = tuple[str, str, tuple[tuple[str, str], ...]]


@pytest.fixture(scope="module")
def pages(tmp_path_factory) -> Path:
    assert not (FRONTEND / "dev-pages" / "about.html").exists(), "a local dev-pages/about.html replaces the About template in the build; move it aside before running"
    out = tmp_path_factory.mktemp("base_css_build") / "pages"
    built = subprocess.run([str(VITE), "build", "--outDir", str(out)], cwd=FRONTEND, capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    return out


def _built_base(out: Path) -> str:
    base_source = FRONTEND / "src" / "base.css"
    assert base_source.is_file(), f"{base_source} does not exist"
    runner = out / "single_sheet_build.mjs"
    runner.write_text(SINGLE_SHEET_BUILD)
    single = subprocess.run(["node", str(runner)], cwd=FRONTEND, capture_output=True, text=True, timeout=300,
                            env={**os.environ, "VITE_API": VITE_API.as_uri(), "CONFIG": str(FRONTEND / "vite.config.ts"), "FRONTEND": str(FRONTEND), "OUT": str(out / "base"), "INPUT": str(base_source)})
    assert single.returncode == 0, single.stdout + single.stderr
    base_bundles = sorted((out / "base" / "assets").glob("*.css"))
    assert len(base_bundles) == 1, base_bundles
    return base_bundles[0].read_text()


class _StylesheetLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "stylesheet" and attributes.get("href"):
            self.hrefs.append(attributes["href"])


def _linked_bundles(pages: Path) -> list[str]:
    hrefs: set[str] = set()
    for html in pages.rglob("*.html"):
        parser = _StylesheetLinks()
        parser.feed(html.read_text())
        hrefs.update(parser.hrefs)
    return sorted(hrefs)


def _rules(css: str) -> list[Rule]:
    """Every style rule in document order as (enclosing at-rule prelude or "", selector list, ((property, value), ...)), comments dropped and whitespace collapsed."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[Rule] = []

    def walk(text: str, context: str) -> None:
        start = 0
        while (opening := text.find("{", start)) >= 0:
            # a statement at-rule such as `@import "./base.css";` ends at its `;` and is not part of the next prelude
            prelude = " ".join(text[start:opening].split(";")[-1].split())
            depth, end = 1, opening + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(text[end], 0)
                end += 1
            inner = text[opening + 1:end - 1]
            if prelude.startswith("@"):
                walk(inner, prelude)
            else:
                declarations = tuple((prop.strip(), " ".join(value.split())) for prop, _, value in (d.partition(":") for d in inner.split(";")) if value.strip())
                rules.append((context, ", ".join(s.strip() for s in prelude.split(",")), declarations))
            start = end

    walk(css, "")
    return rules


def test_every_linked_page_css_bundle_opens_with_the_built_base_rules_then_page_rules_and_holds_no_import(pages, tmp_path):
    bundles = _linked_bundles(pages)
    # control: the built HTML links exactly the four page sheets' bundles, so the loops cover every one of them
    assert sorted(re.sub(r"^/assets/(.*)-[\w-]{8}\.css$", r"\1", href) for href in bundles) == ["channels", "search", "video", "videos"], bundles
    sheets = {href: (pages / href.lstrip("/")).read_text() for href in bundles}
    # every bundle is judged on what needs no base first, so a missing base.css cannot hide a bundle that does not open on the tokens
    for href, css in sheets.items():
        rules = _rules(css)
        assert "@import" not in css, href
        assert rules and rules[0][1] == ":root" and any(prop == "--paper" for prop, _ in rules[0][2]), (href, rules[:1])

    base = _rules(_built_base(tmp_path))
    # control: the base built alone is the real base, opening on the colour tokens, so the prefix below is not empty
    assert base and base[0][1] == ":root" and any(prop == "--paper" for prop, _ in base[0][2]), base[:1]
    for href, css in sheets.items():
        rules = _rules(css)
        assert rules[:len(base)] == base, (href, next(((i, got, want) for i, (got, want) in enumerate(zip(rules, base)) if got != want), ("bundle shorter than base", len(rules), len(base))))
        # control: the bundle carries page rules after the base, so a bundle that is only the base cannot pass
        assert len(rules) > len(base), (href, len(rules), len(base))
