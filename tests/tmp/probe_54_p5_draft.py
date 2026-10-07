"""Probe: the plan's Phase 5 draft applied to a temporary copy of client/frontend, and wrong variants of it, run through the checkpoint's tests. The report is the failure message."""
from __future__ import annotations

import importlib.util
import json
import shutil
import traceback
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parents[1] / "client" / "frontend"

spec = importlib.util.spec_from_file_location("p5_checkpoint", HERE / "test_frontend_search_page.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

APPLY_MODE = '''
/**
 * Show the mode the state is in: the tag heading, the sort menu (no relevance for tag results), the box and the title.
 */
function applyMode() {
  const tagMode = Boolean(state.tag);
  relevanceOption.hidden = tagMode;
  relevanceOption.disabled = tagMode;
  tagHeading.hidden = !tagMode;
  tagHeading.textContent = tagMode ? `Videos tagged "${state.tag}"` : "";
  input.value = state.query;
  sortSelect.value = state.sort;
  document.title = tagMode
    ? `${state.tag} - Tag - Search - PeerTube - Browser`
    : state.query
      ? `${state.query} - Search - PeerTube - Browser`
      : "Search - PeerTube - Browser";
}
'''

PAGE = [
    ('const sentinel = requireElement<HTMLElement>("search-sentinel");\n',
     'const sentinel = requireElement<HTMLElement>("search-sentinel");\nconst tagHeading = requireElement<HTMLElement>("search-tag");\nconst relevanceOption = sortSelect.querySelector<HTMLOptionElement>(\'option[value="relevance"]\');\nif (!relevanceOption) throw new Error("Missing search page element: relevance sort option");\nconst TAG_DEFAULT_SORT: SearchSort = "published_at";\n'),
    ('  query: (params.get("q") ?? "").trim(),\n  sort: resolveSort(params.get("sort")),\n', '  query: (params.get("q") ?? "").trim(),\n  tag: "",\n  sort: "relevance" as SearchSort,\n'),
    ('input.value = state.query;\nsortSelect.value = state.sort;\n\n// Filled by', 'state.tag = state.query ? "" : (params.get("tag") ?? "").trim();\nstate.sort = resolveSort(params.get("sort"), Boolean(state.tag));\n\n// Filled by'),
    ('startSearch(next, state.sort);', 'startSearch(next, "", state.sort);'),
    ('  if (!state.query) return;\n  startSearch(state.query, resolveSort(sortSelect.value));', '  if (!state.query && !state.tag) return;\n  startSearch(state.query, state.tag, resolveSort(sortSelect.value, Boolean(state.tag)));'),
    ('  state.query = (current.get("q") ?? "").trim();\n  state.sort = resolveSort(current.get("sort"));\n  input.value = state.query;\n  sortSelect.value = state.sort;\n  if (!state.query) {\n    showIdle();\n    return;\n  }\n  void loadPage(1, true);',
     '  state.query = (current.get("q") ?? "").trim();\n  state.tag = state.query ? "" : (current.get("tag") ?? "").trim();\n  state.sort = resolveSort(current.get("sort"), Boolean(state.tag));\n  if (!state.query && !state.tag) {\n    showIdle(false);\n    return;\n  }\n  applyMode();\n  if (state.query && current.has("tag")) pushUrl(true);\n  void loadPage(1, true);'),
    ('if (state.query) {\n  document.title = `${state.query} - Search - PeerTube - Browser`;\n  void loadPage(1, true);\n} else {',
     'if (state.query || state.tag) {\n  applyMode();\n  if (state.query && params.has("tag")) pushUrl(true);\n  void loadPage(1, true);\n} else {'),
    ('function startSearch(query: string, sort: SearchSort) {\n  state.query = query;\n  state.sort = sort;\n  state.page = 1;\n  pushUrl();\n  document.title = `${query} - Search - PeerTube - Browser`;\n  void loadPage(1, true);\n}\n',
     'function startSearch(query: string, tag: string, sort: SearchSort) {\n  state.query = query;\n  state.tag = tag;\n  state.sort = sort;\n  state.page = 1;\n  applyMode();\n  pushUrl();\n  void loadPage(1, true);\n}\n' + APPLY_MODE),
    ('      q: state.query,\n      page,', '      q: state.query,\n      tag: state.tag,\n      page,'),
    ('    setStatus(`No results for "${state.query}".`);', '    setStatus(state.tag ? `No videos tagged "${state.tag}".` : `No results for "${state.query}".`);'),
    ('  setStatus(`Showing ${state.loadedRows} of ${state.total} matched videos.`);', '  setStatus(state.tag ? `Showing ${state.loadedRows} of ${state.total} videos tagged "${state.tag}".` : `Showing ${state.loadedRows} of ${state.total} matched videos.`);'),
    ('function showIdle() {\n  state.query = "";\n', 'function showIdle(updateUrl = true) {\n  state.query = "";\n  state.tag = "";\n'),
    ('  document.title = "Search - PeerTube - Browser";\n  setStatus("Enter a search term to begin.");\n  pushUrl();\n}', '  applyMode();\n  setStatus("Enter a search term to begin.");\n  if (updateUrl) pushUrl();\n}'),
    ('  if (state.query) next.set("q", state.query);\n  if (state.sort !== "relevance") next.set("sort", state.sort);',
     '  if (state.query) next.set("q", state.query);\n  else if (state.tag) next.set("tag", state.tag);\n  if (state.sort !== (state.tag ? TAG_DEFAULT_SORT : "relevance")) next.set("sort", state.sort);'),
    ('function resolveSort(value: string | null): SearchSort {\n  const candidate = (value ?? "").trim() as SearchSort;\n  return SORTS.includes(candidate) ? candidate : "relevance";\n}',
     'function resolveSort(value: string | null, tagMode = false): SearchSort {\n  const candidate = (value ?? "").trim() as SearchSort;\n  if (!SORTS.includes(candidate) || (tagMode && candidate === "relevance")) return tagMode ? TAG_DEFAULT_SORT : "relevance";\n  return candidate;\n}'),
]
DATA = [
    ('  q: string;\n', '  q?: string;\n  tag?: string;\n'),
    ('  const query = options.q.trim();\n  url.searchParams.set("q", query);', '  const tag = (options.tag ?? "").trim();\n  if (tag) url.searchParams.set("tag", tag);\n  else url.searchParams.set("q", (options.q ?? "").trim());'),
]
HTML = [('<section class="search-controls">\n', '<section class="search-controls">\n          <h2 id="search-tag" class="search-tag" hidden></h2>\n')]

PAGE_TS, DATA_TS = "src/pages/search/index.ts", "src/data/search.ts"
# Each wrong variant: edits on top of the draft, by file.
VARIANTS = {
    "data-sends-q-beside-tag": {DATA_TS: [('  if (tag) url.searchParams.set("tag", tag);\n  else url.searchParams.set("q"', '  if (tag) url.searchParams.set("tag", tag);\n  url.searchParams.set("q"')]},
    "q-url-keeps-tag-in-state": {PAGE_TS: [('state.tag = state.query ? "" : (params.get("tag") ?? "").trim();', 'state.tag = (params.get("tag") ?? "").trim();')]},
    "sort-left-out-only-at-relevance": {PAGE_TS: [('if (state.sort !== (state.tag ? TAG_DEFAULT_SORT : "relevance"))', 'if (state.sort !== "relevance")')]},
    "tag-default-sort-relevance": {PAGE_TS: [('return tagMode ? TAG_DEFAULT_SORT : "relevance";', 'return "relevance";')]},
    "relevance-only-hidden": {PAGE_TS: [("  relevanceOption.disabled = tagMode;\n", "")]},
    "relevance-never-restored": {PAGE_TS: [("  relevanceOption.hidden = tagMode;\n  relevanceOption.disabled = tagMode;\n", "  if (tagMode) relevanceOption.hidden = true;\n  if (tagMode) relevanceOption.disabled = true;\n")]},
    "heading-never-hidden": {PAGE_TS: [("  tagHeading.hidden = !tagMode;\n", "  if (tagMode) tagHeading.hidden = false;\n")]},
    "tag-status-in-text-wording": {PAGE_TS: [('`Showing ${state.loadedRows} of ${state.total} videos tagged "${state.tag}".`', '`Showing ${state.loadedRows} of ${state.total} matched videos.`'), ('`No videos tagged "${state.tag}".`', '`No results for "${state.query}".`')]},
    "popstate-to-idle-pushes": {PAGE_TS: [("    showIdle(false);\n", "    showIdle();\n")]},
    "popstate-into-tag-pushes": {PAGE_TS: [('  applyMode();\n  if (state.query && current.has("tag")) pushUrl(true);\n  void loadPage(1, true);\n});', "  startSearch(state.query, state.tag, state.sort);\n});")]},
    "a-tag-branch-renders-no-cards": {PAGE_TS: [('  const markup = rows.map(renderSearchCard).join("");', '  const markup = state.tag ? "" : rows.map(renderSearchCard).join("");')]},
    "b-popstate-keeps-the-old-grid": {PAGE_TS: [("  void loadPage(1, true);\n});", "  void loadPage(1, false);\n});")]},
    "c-popstate-reads-tag-before-q": {PAGE_TS: [('  state.query = (current.get("q") ?? "").trim();\n  state.tag = state.query ? "" : (current.get("tag") ?? "").trim();\n', '  state.tag = (current.get("tag") ?? "").trim();\n  state.query = state.tag ? "" : (current.get("q") ?? "").trim();\n')]},
    "d-popstate-keeps-the-first-tag": {PAGE_TS: [('  state.tag = state.query ? "" : (current.get("tag") ?? "").trim();\n', '  state.tag = state.query ? "" : state.tag || (current.get("tag") ?? "").trim();\n')]},
    "popstate-q-tag-leaves-tag-in-url": {PAGE_TS: [('  if (state.query && current.has("tag")) pushUrl(true);\n', "")]},
    "popstate-q-tag-pushes": {PAGE_TS: [('  if (state.query && current.has("tag")) pushUrl(true);\n', '  if (state.query && current.has("tag")) pushUrl();\n')]},
    "heading-keeps-the-first-tag": {PAGE_TS: [("  tagHeading.textContent = tagMode ?", "  if (!tagHeading.textContent) tagHeading.textContent = tagMode ?")]},
    "pushed-tag-unencoded": {PAGE_TS: [('  else if (state.tag) next.set("tag", state.tag);', '  else if (state.tag) next.set("tag", "TAGSLOT");'), ("`?${next.toString()}`", '`?${next.toString().replace("TAGSLOT", state.tag)}`')]},
    "request-tag-unencoded": {DATA_TS: [('  if (tag) url.searchParams.set("tag", tag);\n', "  if (tag) url.search += `&tag=${tag}`;\n")]},
    "submit-keeps-tag": {PAGE_TS: [('startSearch(next, "", state.sort);', "startSearch(next, state.tag, state.sort);"), ('  else if (state.tag) next.set("tag", state.tag);', '  if (state.tag) next.set("tag", state.tag);')]},
    "url-keeps-original-tag-beside-q": {PAGE_TS: [('  else if (state.tag) next.set("tag", state.tag);', '  else if (state.tag) next.set("tag", state.tag);\n  if (state.query && params.get("tag")) next.set("tag", params.get("tag") ?? "");')]},
    "q-tag-url-not-rewritten": {PAGE_TS: [('  if (state.query && params.has("tag")) pushUrl(true);\n', "")]},
    "q-tag-url-pushed-not-replaced": {PAGE_TS: [('  if (state.query && params.has("tag")) pushUrl(true);\n', '  if (state.query && params.has("tag")) pushUrl();\n')]},
}


def _edit(path: Path, edits: list[tuple[str, str]]):
    text = path.read_text()
    for old, new in edits:
        assert text.count(old) == 1, (path, old, text.count(old))
        text = text.replace(old, new)
    path.write_text(text)


def _tree(root: Path, extra: dict) -> Path:
    shutil.copytree(FRONTEND / "src", root / "src")
    shutil.copy(FRONTEND / "search.html", root / "search.html")
    _edit(root / PAGE_TS, PAGE + extra.get(PAGE_TS, []))
    _edit(root / DATA_TS, DATA + extra.get(DATA_TS, []))
    _edit(root / "search.html", HTML)
    return root


def _outcomes(page: Path, record: list | None = None) -> dict:
    run = cp._run
    if record is not None:
        def recording(*args, **kwargs):
            report = run(*args, **kwargs)
            record.append(report)
            return report
        cp._run = recording
    out = {}
    try:
        for name in [n for n in dir(cp) if n.startswith("test_")]:
            try:
                getattr(cp, name)(page)
                out[name] = "PASS"
            except AssertionError as error:
                frame = [f for f in traceback.extract_tb(error.__traceback__) if f.filename.endswith("test_frontend_search_page.py")][-1]
                out[name] = f"RED line {frame.lineno}: {str(error).splitlines()[0][:160]}"
    finally:
        cp._run = run
    return out


def test_probe(tmp_path):
    lines = []
    record = []
    draft = _tree(tmp_path / "draft", {})
    draft_out = tmp_path / "draft_out"
    draft_out.mkdir()
    lines.append("DRAFT: " + json.dumps(_outcomes(cp._prepare(draft, draft_out), record), indent=1))
    for report in record:
        lines.append(json.dumps({"errors": report["errors"], "missing": report["missing"], "phases": [{k: p[k] for k in ("name", "requests", "history", "title", "status", "heading", "relevance", "cards", "address")} for p in report["phases"]]}))
    for name, extra in VARIANTS.items():
        out = tmp_path / f"{name}_out"
        out.mkdir()
        results = _outcomes(cp._prepare(_tree(tmp_path / name, extra), out))
        lines.append(f"VARIANT {name}: " + json.dumps({k.removeprefix("test_")[:50]: v for k, v in results.items() if v != "PASS"}, indent=1))
    pytest.fail("\n".join(lines))
