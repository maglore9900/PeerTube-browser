"""Probe: the card bundle in both builds today, html.parser on renderVideoCard, and the fit harness's stubs on hand-built rows."""
from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"

CALL_RUNNER = """
const m = await import(process.env.BUNDLE);
const results = JSON.parse(process.env.CALLS).map(([name, ...args]) => {
  if (typeof m[name] !== "function") return { error: `${name} is not exported` };
  try { const value = m[name](...args); return value === undefined ? { undefined: true } : { value }; } catch (e) { return { error: String(e) }; }
});
process.stdout.write(JSON.stringify({ exports: Object.keys(m).sort(), results, node: [new URLSearchParams({ tag: "a b&c" }).toString(), Array.from("\\u{1F600}".repeat(64)).length, "\\u{1F600}".repeat(64).length] }) + "\\n");
"""

STUB_RUNNER = r"""
class Node {} class Element extends Node {} class HTMLElement extends Element {}
const kids = [];
const el = (cls, w) => { const e = Object.setPrototypeOf({ cls, w, hidden: false }, HTMLElement.prototype); return e; };
const plain = { a: 1 };
process.stdout.write(JSON.stringify({ inst: el("x") instanceof HTMLElement, plain: plain instanceof HTMLElement, mo: typeof MutationObserver, ro: typeof ResizeObserver, qm: typeof queueMicrotask }) + "\n");
"""


def _build(out: Path, dev: bool) -> Path:
    target = out / f"card_{'dev' if dev else 'prod'}.mjs"
    run = subprocess.run([str(ESBUILD), str(FRONTEND / "src" / "components" / "video-card.ts"), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={target}",
                          f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", f"--define:import.meta.env.DEV={'true' if dev else 'false'}"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return target


class _Tree(HTMLParser):
    VOID = {"img", "br", "input", "meta", "link", "hr", "source", "wbr", "path", "rect", "circle"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": None, "attrs": {}, "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1]["children"].append({"tag": tag, "attrs": dict(attrs), "children": []})

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1]["children"].append(data)


def _outline(node, depth=0):
    if isinstance(node, str):
        return []
    lines = [("  " * depth) + f"{node['tag']} {node['attrs'].get('class', '')}"] if node["tag"] else []
    for c in node["children"]:
        lines += _outline(c, depth + 1)
    return lines


def test_probe(tmp_path):
    env = {"PATH": os.environ.get("PATH", "")}
    seen = {}
    for dev in (False, True):
        bundle = _build(tmp_path, dev)
        (tmp_path / "call.mjs").write_text(CALL_RUNNER)
        calls = [["tagSearchUrl", "a b&c"], ["renderTagChips", ["a"]], ["videoPageUrl", {"video_uuid": "u", "instance_domain": "d"}, "http://api.example"],
                 ["renderVideoCard", {"video_uuid": "u1", "instance_domain": "tube.example", "title": "T", "tags": ["one", "two"]}, {"actions": True, "apiParam": "http://api.example"}]]
        proc = subprocess.run(["node", str(tmp_path / "call.mjs")], capture_output=True, text=True, env={**env, "BUNDLE": str(bundle), "CALLS": json.dumps(calls)})
        seen[dev] = (proc.returncode, proc.stderr[-500:], json.loads(proc.stdout.splitlines()[-1]) if proc.stdout else None)
    card = seen[False][2]["results"][3]["value"]
    tree = _Tree()
    tree.feed(card)
    (tmp_path / "stub.mjs").write_text(STUB_RUNNER)
    stub = subprocess.run(["node", str(tmp_path / "stub.mjs")], capture_output=True, text=True, env=env)
    assert False, json.dumps({"prod": seen[False], "dev_results": seen[True][2]["results"][:3], "outline": _outline(tree.root), "stub": stub.stdout + stub.stderr}, indent=1)
