"""`renderVideoCard` (`components/video-card.ts`) reports the Dislike button's pressed state, run in node.

- With `actions: true` on a keyed row, the `[data-card-action="dislike"]` button carries `aria-pressed="true"` when `reaction` is `"disliked"`, and `aria-pressed="false"` when it is `null`, `"liked"` or omitted.
- `npx tsc --noEmit` in client/frontend reports no error in `src/components/video-card.ts`. The project already has type errors in three unrelated page files, so the check is scoped to the changed file.
"""
from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
ROW = {"video_uuid": "9c1f6a2e-0000-4000-8000-000000000040", "instance_domain": "videos.example", "title": "A video"}

RUNNER = """
const m = await import(process.env.BUNDLE);
const row = JSON.parse(process.env.ROW);
const out = {};
for (const [name, reaction] of [["disliked", "disliked"], ["null", null], ["liked", "liked"]]) out[name] = m.renderVideoCard(row, { actions: true, reaction });
out.omitted = m.renderVideoCard(row, { actions: true });
process.stdout.write(JSON.stringify(out));
"""


class _Buttons(HTMLParser):
    """Collect the attributes of every `data-card-action` button, keyed by its action."""

    def __init__(self) -> None:
        super().__init__()
        self.found: dict[str, list[dict]] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "button" and "data-card-action" in attributes:
            self.found.setdefault(attributes["data-card-action"], []).append(attributes)


def _buttons(html: str) -> dict[str, list[dict]]:
    parser = _Buttons()
    parser.feed(html)
    return parser.found


def _render(tmp_path: Path) -> dict[str, str]:
    entry = tmp_path / "entry.ts"
    entry.write_text(f'export {{ renderVideoCard }} from "{FRONTEND}/src/components/video-card.ts";\n')
    bundle = tmp_path / "bundle.mjs"
    subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", f"--outfile={bundle}", "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER)
    proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=60, env={"BUNDLE": str(bundle), "ROW": json.dumps(ROW), "PATH": os.environ.get("PATH", "")})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_dislike_button_is_pressed_only_when_the_reaction_is_disliked(tmp_path):
    cards = {name: _buttons(html) for name, html in _render(tmp_path).items()}
    for name, buttons in cards.items():
        assert len(buttons.get("dislike", [])) == 1, (name, buttons)  # control: the keyed row renders one Dislike button

    assert cards["disliked"]["dislike"][0].get("aria-pressed") == "true", cards["disliked"]  # C1
    assert cards["null"]["dislike"][0].get("aria-pressed") == "false", cards["null"]  # C1: home's case
    assert cards["liked"]["dislike"][0].get("aria-pressed") == "false", cards["liked"]  # C1: a like is not a dislike
    assert cards["omitted"]["dislike"][0].get("aria-pressed") == "false", cards["omitted"]  # C1: no reaction option at all
    assert cards["liked"]["like"][0].get("aria-pressed") == "true"  # control: the Like button still reports its own state
    assert cards["disliked"]["like"][0].get("aria-pressed") == "false"  # control: the dislike does not press Like


def test_the_type_check_reports_no_error_in_the_video_card_component():
    proc = subprocess.run(["npx", "tsc", "--noEmit"], cwd=FRONTEND, capture_output=True, text=True, timeout=600)
    assert proc.returncode in (0, 2), (proc.returncode, proc.stdout, proc.stderr)  # 0 clean, 2 diagnostics reported; anything else means tsc did not check
    assert [line for line in proc.stdout.splitlines() if "src/components/video-card.ts" in line] == []
