"""Phase 1 of issue 28: the feed card and the channels row carry their own class names, styled with the rules the old names had.

Markup (C1):
- `renderVideoCard`, run in node on a row with a channel avatar and on one without, returns HTML holding `class="card-title"` on the title, `class="card-channel"` and `class="card-avatar"`, and none of `video-title`, `channel-meta` or `channel-avatar`.
- The channels page module, run in node against a stubbed `/api/channels` answering one row, renders a `#channels-body` row whose instance-domain element carries `class="channel-domain"`, and holds no `channel-meta`.

Styles (C2):
- In `videos.css`, `.card-title`, `.card-channel`, `.card-avatar` and `.card-avatar img` each hold exactly the declarations `.video-title`, `.channel-meta`, `.channel-avatar` and `.channel-avatar img` held at the pinned pre-change commit; in `channels.css`, `.channel-domain` holds exactly what `.channel-meta` held there. No selector in either sheet still names the sheet's old classes.

The channels runner stubs the browser platform node lacks: a `document` holding plain recording elements for the four ids the module requires, `window.location`, and `fetch`, which answers `/api/channels` with the one-row payload and 404 for anything else.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
# The last commit before the renames; its sheets are the source of the declarations the new names must carry.
PRE_CHANGE_SHA = "5bdec949293b735cf2b9bb71b1eafea58f582830"
TITLE = "Fixture card title"
CHANNEL = "Lofi Beats Radio"
DOMAIN = "tube.example"
AVATAR = "https://tube.example/avatar.png"
CARD_ROWS = [
    {"video_uuid": "uuid-1", "instance_domain": DOMAIN, "title": TITLE, "channel_name": "lofi_beats", "channel_display_name": CHANNEL, "channel_avatar_url": AVATAR},
    # no avatar: the card renders initials instead of an <img> inside the avatar element
    {"video_uuid": "uuid-2", "instance_domain": DOMAIN, "title": TITLE, "channel_name": "lofi_beats", "channel_display_name": CHANNEL},
]
CHANNEL_ROW = {"channel_id": "c1", "channel_name": "lofi_beats", "channel_url": None, "display_name": CHANNEL, "instance_domain": DOMAIN,
               "videos_count": 3, "followers_count": 12, "avatar_url": None, "health_status": None, "health_checked_at": None, "health_error": None,
               "last_error": None, "last_error_at": None, "last_error_source": None}
VIDEOS_RENAMES = {".card-title": ".video-title", ".card-channel": ".channel-meta", ".card-avatar": ".channel-avatar", ".card-avatar img": ".channel-avatar img"}
CHANNELS_RENAMES = {".channel-domain": ".channel-meta"}

CARD_RUNNER = """
const m = await import(process.env.BUNDLE);
process.stdout.write(JSON.stringify({ cards: JSON.parse(process.env.ROWS).map((row) => m.renderVideoCard(row)) }) + "\\n");
"""

CHANNELS_RUNNER = """
const element = () => ({ innerHTML: "", textContent: "" });
const byId = new Map(["channels-body", "summary-counts", "summary-meta", "page-status"].map((id) => [id, element()]));
globalThis.window = { location: { origin: process.env.BASE, search: "" }, setTimeout, clearTimeout };
globalThis.document = { getElementById: (id) => byId.get(id) ?? null, querySelectorAll: () => [] };
const requested = [];
globalThis.fetch = async (input) => {
  const url = new URL(String(input), process.env.BASE);
  requested.push(url.pathname);
  if (url.pathname === "/api/channels") return new Response(process.env.PAYLOAD, { status: 200, headers: { "content-type": "application/json" } });
  return new Response("{}", { status: 404 });
};
await import(process.env.BUNDLE);
// The stubbed fetch resolves at once, so the page's load has rendered within a few macrotasks.
for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
process.stdout.write(JSON.stringify({ requested, body: byId.get("channels-body").innerHTML }) + "\\n");
"""


@pytest.fixture(scope="module")
def bundles(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("class_renames")
    defines = [f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"]
    for source, name in ((FRONTEND / "src" / "components" / "video-card.ts", "card.mjs"), (FRONTEND / "src" / "pages" / "channels" / "index.ts", "channels.mjs")):
        subprocess.run([str(ESBUILD), str(source), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / name}", *defines],
                       check=True, capture_output=True)
    (out / "card_runner.mjs").write_text(CARD_RUNNER)
    (out / "channels_runner.mjs").write_text(CHANNELS_RUNNER)
    return out


def _node(runner: Path, bundle: Path, **env: str) -> dict:
    proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=60,
                          env={"BASE": BASE, "BUNDLE": str(bundle), "PATH": os.environ.get("PATH", ""), **env})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _rules(css: str) -> dict[tuple[str, str], dict[str, str]]:
    """(enclosing at-rule prelude or "", selector) -> {property: value}, comments dropped and whitespace collapsed; a selector declared twice in one context merges, later winning."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: dict[tuple[str, str], dict[str, str]] = {}

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
                declarations = {}
                for declaration in inner.split(";"):
                    if ":" in declaration:
                        prop, value = declaration.split(":", 1)
                        declarations[prop.strip()] = " ".join(value.split())
                for selector in prelude.split(","):
                    rules.setdefault((context, " ".join(selector.split())), {}).update(declarations)
            start = end

    walk(css, "")
    return rules


def _sheet(name: str) -> dict[tuple[str, str], dict[str, str]]:
    return _rules((FRONTEND / "src" / name).read_text())


def _pre_change_sheet(name: str) -> dict[tuple[str, str], dict[str, str]]:
    shown = subprocess.run(["git", "-C", str(ROOT), "show", f"{PRE_CHANGE_SHA}:client/frontend/src/{name}"], capture_output=True, text=True)
    assert shown.returncode == 0, shown.stderr
    return _rules(shown.stdout)


def _selectors_naming(rules: dict[tuple[str, str], dict[str, str]], classes: set[str]) -> list[tuple[str, str]]:
    pattern = re.compile(r"\.(" + "|".join(re.escape(c.lstrip(".")) for c in classes) + r")(?![\w-])")
    return [key for key in rules if pattern.search(key[1])]


def test_the_feed_card_with_or_without_an_avatar_carries_card_title_card_channel_and_card_avatar_and_none_of_the_video_page_names(bundles):
    cards = _node(bundles / "card_runner.mjs", bundles / "card.mjs", ROWS=json.dumps(CARD_ROWS))["cards"]

    assert len(cards) == 2, cards
    for card in cards:
        # control: the card rendered the row, so the absences below are read from real markup
        assert TITLE in card and CHANNEL in card, card
        assert re.search(r'class="card-title"[^>]*>\s*' + re.escape(TITLE), card), card  # C1
        assert 'class="card-channel"' in card, card  # C1
        assert 'class="card-avatar"' in card, card  # C1
        assert "video-title" not in card, card  # C1
        assert "channel-meta" not in card, card  # C1
        assert "channel-avatar" not in card, card  # C1
    # the avatar image still sits inside the renamed avatar element, so `.card-avatar img` reaches it
    assert re.search(r'class="card-avatar"[^>]*>\s*<img src="' + re.escape(AVATAR) + '"', cards[0]), cards[0]  # C1


def test_the_channels_row_carries_channel_domain_on_its_instance_domain_and_no_channel_meta(bundles):
    page = _node(bundles / "channels_runner.mjs", bundles / "channels.mjs", PAYLOAD=json.dumps({"rows": [CHANNEL_ROW], "total": 1}))
    body = page["body"]

    # control: the page asked for its channels and rendered the row, so an empty or loading table cannot pass
    assert "/api/channels" in page["requested"], page["requested"]
    assert CHANNEL in body and DOMAIN in body, body
    assert re.search(r'class="channel-domain"[^>]*>\s*' + re.escape(DOMAIN) + r"\s*<", body), body  # C1
    assert "channel-meta" not in body, body  # C1


def test_the_renamed_rules_hold_exactly_the_old_rules_pre_change_declarations_and_no_old_selector_remains():
    old_videos, new_videos = _pre_change_sheet("videos.css"), _sheet("videos.css")
    old_channels, new_channels = _pre_change_sheet("channels.css"), _sheet("channels.css")

    # control: the pinned commit's sheets hold the old rules with their known values, so an equality below cannot be two empty maps
    assert old_videos[("", ".video-title")]["-webkit-line-clamp"] == "2", old_videos.get(("", ".video-title"))
    assert old_videos[("", ".channel-meta")]["display"] == "flex", old_videos.get(("", ".channel-meta"))
    assert old_videos[("", ".channel-avatar")]["width"] == "34px", old_videos.get(("", ".channel-avatar"))
    assert old_videos[("", ".channel-avatar img")]["object-fit"] == "cover", old_videos.get(("", ".channel-avatar img"))
    assert old_channels[("", ".channel-meta")]["font-size"] == "0.85rem", old_channels.get(("", ".channel-meta"))
    for new, old in VIDEOS_RENAMES.items():
        assert new_videos.get(("", new)) == old_videos[("", old)], (new, new_videos.get(("", new)), old_videos[("", old)])  # C2
    for new, old in CHANNELS_RENAMES.items():
        assert new_channels.get(("", new)) == old_channels[("", old)], (new, new_channels.get(("", new)), old_channels[("", old)])  # C2
    assert _selectors_naming(new_videos, set(VIDEOS_RENAMES.values())) == [], "videos.css still styles an old card class"  # C2
    assert _selectors_naming(new_channels, set(CHANNELS_RENAMES.values())) == [], "channels.css still styles .channel-meta"  # C2
