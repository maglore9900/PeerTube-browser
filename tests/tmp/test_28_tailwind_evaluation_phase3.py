"""Phase 3 of issue 28: the committed `client/frontend/dist/` is a current build, and every page in it resolves its styles as the pre-change dist did, apart from the completed `.visually-hidden`.

Rung 3: the committed dist as served, compared with the dist at the pinned pre-change commit read through `git show`. Both sides went through the same Vite and esbuild, so minifier rewrites cancel out.

Current build: with no local `dev-pages/about.html`, a fresh `vite build --outDir <tmp>` emits exactly the asset file names the committed dist holds, and each of the seven HTML pages exactly as committed. Controls: the committed dist has no `dev-pages/about.html`, and both dists serve exactly the seven pages: index, videos, likes, search, video page, channels and the About template.

Cascade (C1), per page: the stylesheets the page links are applied in document order, and each (at-rule, selector) resolves to the declarations that end up on it, last occurrence winning. The phase-1 renames are read under their old names (`card-*` in the videos bundle, `channel-domain` in the channels bundle). Every selector the page had before resolves to exactly the same declarations. The exception is top-level `.visually-hidden`, which holds the nine declarations of the complete form, each checked. A selector new to a page names at least one class, and only classes that occur nowhere in the page's HTML or in the scripts it loads.

Load order (C2): the committed `search.html` links the search CSS bundle before the videos CSS bundle.

Known limit, from the plan's gotcha: the comparison works per selector. A moved rule that now competes on the same element with a different selector of equal specificity is invisible to it, so that check stays with the verification step.
"""
from __future__ import annotations

import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
DIST = FRONTEND / "dist"
VITE = FRONTEND / "node_modules" / ".bin" / "vite"
# The last commit before the build; its dist is the cascade every page must keep. Pinned for the life of the build.
PRE_CHANGE_SHA = "5bdec949293b735cf2b9bb71b1eafea58f582830"
PAGES = ("index.html", "videos.html", "likes.html", "search.html", "video-page.html", "channels.html", "dev-pages/about.template.html")
# Phase-1 renames per CSS bundle, new name -> old name; the video page's own bundle keeps the old names and is not mapped.
RENAMES = {"videos": {".card-title": ".video-title", ".card-channel": ".channel-meta", ".card-avatar": ".channel-avatar"}, "channels": {".channel-domain": ".channel-meta"}}
VISUALLY_HIDDEN = ("", ".visually-hidden")
# Requirement item 3's complete form as esbuild minifies it: `clip: rect(0, 0, 0, 0)` loses its spaces.
COMPLETE_VISUALLY_HIDDEN = {"position": "absolute", "width": "1px", "height": "1px", "padding": "0", "margin": "-1px", "overflow": "hidden", "clip": "rect(0,0,0,0)", "white-space": "nowrap", "border": "0"}

Rule = tuple[str, tuple[str, ...], dict[str, str]]


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stylesheets: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "stylesheet" and attributes.get("href"):
            self.stylesheets.append(attributes["href"])
        if (tag == "script" and attributes.get("src")) or (tag == "link" and attributes.get("rel") == "modulepreload" and attributes.get("href")):
            self.scripts.append(attributes.get("src") or attributes["href"])


def _parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


def _old(rel: str) -> str:
    shown = subprocess.run(["git", "-C", str(ROOT), "show", f"{PRE_CHANGE_SHA}:client/frontend/dist/{rel}"], capture_output=True, text=True)
    assert shown.returncode == 0, shown.stderr
    return shown.stdout


def _new(rel: str) -> str:
    return (DIST / rel).read_text()


def _bundle(href: str) -> str:
    return re.sub(r"^/assets/(.+)-[\w-]{8}\.css$", r"\1", href)


def _rules(css: str) -> list[Rule]:
    """Every style rule in document order as (enclosing at-rule prelude or "", selectors, {property: value}), comments dropped and whitespace collapsed."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[Rule] = []

    def walk(text: str, context: str) -> None:
        start = 0
        while (opening := text.find("{", start)) >= 0:
            prelude = " ".join(text[start:opening].split(";")[-1].split())
            depth, end = 1, opening + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(text[end], 0)
                end += 1
            inner = text[opening + 1:end - 1]
            if prelude.startswith("@"):
                walk(inner, prelude)
            else:
                declarations = {prop.strip(): " ".join(value.split()) for prop, _, value in (d.partition(":") for d in inner.split(";")) if value.strip()}
                rules.append((context, tuple(" ".join(s.split()) for s in re.split(r",(?![^()]*\))", prelude)), declarations))
            start = end

    walk(css, "")
    return rules


def _resolve(rules: list[Rule]) -> dict[tuple[str, str], dict[str, str]]:
    """(at-rule prelude or "", selector) -> the declarations that end up on it: every top-level rule for the selector plus every rule for it in that at-rule, merged in document order, last occurrence winning."""
    # rat-tail: each at-rule is resolved alone with the top level, though a 720px viewport also matches the 900px and 1100px blocks; parsing media queries into viewport scenarios is the upgrade if overlapping blocks ever share a selector.
    keys = {(context, selector) for context, selectors, _ in rules for selector in selectors}
    resolved: dict[tuple[str, str], dict[str, str]] = {}
    for context, selector in keys:
        merged: dict[str, str] = {}
        for rule_context, selectors, declarations in rules:
            if selector in selectors and rule_context in ("", context):
                merged.update(declarations)
        resolved[(context, selector)] = merged
    return resolved


def _cascade(read, page: str) -> dict[tuple[str, str], dict[str, str]]:
    rules: list[Rule] = []
    for href in _parse(read(page)).stylesheets:
        renames = RENAMES.get(_bundle(href), {})
        for context, selectors, declarations in _rules(read(href.lstrip("/"))):
            rules.append((context, tuple(re.sub(r"\.[\w-]+", lambda m: renames.get(m.group(0), m.group(0)), s) for s in selectors), declarations))
    return _resolve(rules)


def _served_markup(page: str) -> str:
    """The committed page's HTML plus every script it loads: its module scripts, its modulepreloads, and each `./chunk.js` those import."""
    pending, scripts = [src.lstrip("/") for src in _parse(_new(page)).scripts], {}
    while pending:
        rel = pending.pop()
        if rel not in scripts:
            scripts[rel] = _new(rel)
            pending += ["assets/" + name for name in re.findall(r"""["'`]\./([\w.-]+\.js)["'`]""", scripts[rel])]
    return "\n".join([_new(page), *scripts.values()])


def _uses(markup: str, cls: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(cls) + r"(?![\w-])", markup) is not None


def test_the_committed_dist_holds_exactly_the_assets_a_fresh_build_emits_and_no_about_override(tmp_path):
    assert not (FRONTEND / "dev-pages" / "about.html").exists(), "a local dev-pages/about.html replaces the About template in the build; move it aside before running"
    out = tmp_path / "dist"
    built = subprocess.run([str(VITE), "build", "--outDir", str(out)], cwd=FRONTEND, capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    # control: the committed About page is the template build, not a local override
    assert not (DIST / "dev-pages" / "about.html").exists()
    # the phase's own claim, and the premise the cascade test rests on: content-hashed names match, so the committed dist is a build of the tree as it stands
    assert sorted(p.name for p in (DIST / "assets").iterdir()) == sorted(p.name for p in (out / "assets").iterdir())
    # the pages carry no content hash, so a hand-edited committed page is caught only by comparing it with the build's; two builds reproduce every page byte for byte
    assert [page for page in PAGES if _new(page) != (out / page).read_text()] == []


def test_both_dists_serve_exactly_the_seven_pages():
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", PRE_CHANGE_SHA, "client/frontend/dist"], capture_output=True, text=True)
    assert listed.returncode == 0, listed.stderr
    old_pages = sorted(path.removeprefix("client/frontend/dist/") for path in listed.stdout.split() if path.endswith(".html"))
    new_pages = sorted(str(path.relative_to(DIST)) for path in DIST.rglob("*.html"))
    # control: the cascade test below is parametrized over every page either dist serves
    assert old_pages == sorted(PAGES), old_pages
    assert new_pages == sorted(PAGES), new_pages


@pytest.mark.parametrize("page", PAGES)
def test_every_selector_a_page_had_resolves_as_before_with_visually_hidden_in_its_complete_form_and_new_selectors_unused_there(page):
    old, new = _cascade(_old, page), _cascade(_new, page)

    # control: both dists link stylesheets for the page and the old cascade carries the colour tokens, so nothing below compares empty maps
    assert _parse(_old(page)).stylesheets and _parse(_new(page)).stylesheets, page
    assert old[("", ":root")]["--paper"] == "#f6f2ea", old.get(("", ":root"))
    changed = {key: (old[key], new.get(key)) for key in old if key != VISUALLY_HIDDEN and new.get(key) != old[key]}
    assert changed == {}, (page, changed)  # C1

    if VISUALLY_HIDDEN in old or VISUALLY_HIDDEN in new:
        hidden = new.get(VISUALLY_HIDDEN) or {}
        for prop, value in COMPLETE_VISUALLY_HIDDEN.items():
            assert hidden.get(prop) == value, (page, prop, hidden)  # C1
        assert sorted(hidden) == sorted(COMPLETE_VISUALLY_HIDDEN), (page, hidden)  # C1

    markup = _served_markup(page)
    # control: the scan reads the page's real markup, which uses the header nav on every page
    assert _uses(markup, "header-nav"), page
    used = {key: [cls for cls in re.findall(r"\.([\w-]+)", key[1]) if _uses(markup, cls)] for key in new if key not in old}
    assert {key: classes for key, classes in used.items() if classes or not re.search(r"\.[\w-]", key[1])} == {}, (page, used)  # C1


def test_search_html_links_the_search_css_before_the_videos_css():
    bundles = [_bundle(href) for href in _parse(_new("search.html")).stylesheets]

    assert "search" in bundles and "videos" in bundles, bundles  # C2
    assert bundles.index("search") < bundles.index("videos"), bundles  # C2
